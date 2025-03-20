from flask import Flask, jsonify, request
from flask_cors import CORS
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove
)
from pydicom.dataset import Dataset
import os
import time
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Initialize Flask app with a static folder
app = Flask(__name__, static_folder='static')
CORS(app)

# PACS connection details
PACS_AE_TITLE = "MYPACS"
PACS_IP = "127.0.0.1"
PACS_PORT = 104

# Client AE details (for receiving images)
CLIENT_AE_TITLE = "TESTSCU2"
CLIENT_PORT = 11119

# Global variable to track the SCP server instance (for receiving images)
scp_server = None

# ---------------------------
# SCP (Storage) functions
# ---------------------------
def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    patient_id = ds.get("PatientID", "unknown").strip()
    folder_name = os.path.join("static", f"retrieved_{patient_id}")
    os.makedirs(folder_name, exist_ok=True)
    filename = os.path.join(folder_name, f"{ds.SOPInstanceUID}.dcm")
    ds.save_as(filename, write_like_original=False)
    logging.info("Received and saved: %s", filename)
    return 0x0000  # Success

def start_scp_server():
    global scp_server
    ae = AE(ae_title=CLIENT_AE_TITLE)
    # Add all expected storage contexts (as SCP)
    for context in StoragePresentationContexts[:50]:
        ae.add_supported_context(context.abstract_syntax, scp_role=True, scu_role=False)
    handlers = [(evt.EVT_C_STORE, handle_store)]
    logging.info(f"Starting DICOM C-STORE SCP on port {CLIENT_PORT} with AE Title {CLIENT_AE_TITLE}")
    scp_server = ae.start_server(("0.0.0.0", CLIENT_PORT), block=False, evt_handlers=handlers)
    return scp_server

def stop_scp_server():
    global scp_server
    if scp_server:
        logging.info("Stopping DICOM C-STORE SCP on port %d", CLIENT_PORT)
        scp_server.shutdown()
        scp_server = None

def wait_for_files(folder, timeout=10, consecutive=2, poll_interval=0.5):
    """
    Poll the folder until the number of DICOM files remains the same for a given number
    of consecutive polls or until timeout is reached.
    """
    stable_count = 0
    previous_count = -1
    start_time = time.time()
    current_files = []
    while time.time() - start_time < timeout:
        if os.path.exists(folder):
            current_files = [fname for fname in os.listdir(folder) if fname.endswith('.dcm')]
            current_count = len(current_files)
            if current_count == previous_count:
                stable_count += 1
            else:
                stable_count = 0
                previous_count = current_count
            if stable_count >= consecutive:
                break
        time.sleep(poll_interval)
    return current_files

# ---------------------------
# API Endpoint
# ---------------------------
@app.route('/api/images', methods=['GET'])
def get_images():
    patient_id = request.args.get('patientId')
    if not patient_id:
        return jsonify({'error': 'PatientID is required'}), 400
    patient_id = patient_id.strip()
    image_urls = []

    # (Re)start our SCP server to receive images
    stop_scp_server()
    start_scp_server()
    time.sleep(1)  # Give a moment for SCP to start

    # 1. First association: send a C-FIND to verify the patient exists.
    ae_find = AE(ae_title="MY_CLIENT")
    ae_find.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
    logging.info("Associating with PACS for C-FIND...")
    assoc_find = ae_find.associate(PACS_IP, PACS_PORT, ae_title=PACS_AE_TITLE)
    if assoc_find.is_established:
        query_ds = Dataset()
        query_ds.QueryRetrieveLevel = "PATIENT"
        query_ds.PatientID = patient_id
        logging.info("Sending C-FIND for PatientID: %s", patient_id)
        found = False
        try:
            for status, identifier in assoc_find.send_c_find(query_ds, PatientRootQueryRetrieveInformationModelFind):
                logging.debug("C-FIND Response: %s, Identifier: %s", status, identifier)
                if status and status.Status in (0xFF00, 0xFF01):
                    found = True
                    break
        except Exception as e:
            logging.error("Error during C-FIND: %s", str(e))
        assoc_find.release()
        if not found:
            stop_scp_server()
            return jsonify({'images': []})
    else:
        stop_scp_server()
        return jsonify({'error': 'Could not associate with PACS for C-FIND'}), 500

    # 2. Second association: send a C-MOVE request to retrieve images.
    ae_move = AE(ae_title="MY_CLIENT_MOVE")
    # Only request the MOVE context here
    ae_move.add_requested_context(PatientRootQueryRetrieveInformationModelMove)
    logging.info("Associating with PACS for C-MOVE...")
    assoc_move = ae_move.associate(PACS_IP, PACS_PORT, ae_title=PACS_AE_TITLE)
    if assoc_move.is_established:
        move_ds = Dataset()
        move_ds.QueryRetrieveLevel = "PATIENT"
        move_ds.PatientID = patient_id
        logging.info("Sending C-MOVE for PatientID: %s to %s", patient_id, CLIENT_AE_TITLE)
        try:
            completed = False
            for status, identifier in assoc_move.send_c_move(
                move_ds,
                move_aet=CLIENT_AE_TITLE,
                query_model=PatientRootQueryRetrieveInformationModelMove
            ):
                if status:
                    status_code = status.Status
                    logging.info("C-MOVE Response: Status 0x{0:04X}".format(status_code))
                    # You may wish to check for pending (0xFF00) statuses here.
                    if status_code == 0x0000:
                        completed = True
            if not completed:
                logging.error("C-MOVE failed or was incomplete.")
        except Exception as e:
            logging.error("Error during C-MOVE: %s", str(e))
        assoc_move.release()
    else:
        stop_scp_server()
        return jsonify({'error': 'Could not associate with PACS for C-MOVE'}), 500

    # 3. Wait for all images to be received
    dest_folder = os.path.join("static", f"retrieved_{patient_id}")
    files = wait_for_files(dest_folder)
    for fname in files:
        full_url = request.host_url.rstrip('/') + f"/static/retrieved_{patient_id}/{fname}"
        image_urls.append(full_url)

    stop_scp_server()
    return jsonify({'images': image_urls})

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
