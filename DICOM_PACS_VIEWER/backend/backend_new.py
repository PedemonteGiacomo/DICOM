from flask import Flask, jsonify, request
from flask_cors import CORS
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    CTImageStorage, MRImageStorage, ComputedRadiographyImageStorage
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

# Global variable to track the SCP server instance
scp_server = None

# C-STORE handler to store received images
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

# Start the SCP server for receiving images
def start_scp_server():
    global scp_server
    ae = AE(ae_title=CLIENT_AE_TITLE)
    # Add support for all storage contexts (with SCP role)
    for context in StoragePresentationContexts[:50]:
        ae.add_supported_context(context.abstract_syntax, scp_role=True, scu_role=False)
    # Only include the C-STORE handler
    handlers = [(evt.EVT_C_STORE, handle_store)]
    logging.info(f"Starting DICOM C-STORE SCP on port {CLIENT_PORT} with AE Title {CLIENT_AE_TITLE}")
    scp_server = ae.start_server(("0.0.0.0", CLIENT_PORT), block=False, evt_handlers=handlers)
    return scp_server

# Stop the SCP server
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

@app.route('/api/images', methods=['GET'])
def get_images():
    patient_id = request.args.get('patientId')
    if not patient_id:
        return jsonify({'error': 'PatientID is required'}), 400

    patient_id = patient_id.strip()
    image_urls = []

    # Ensure a clean SCP server is running
    stop_scp_server()  # Stop any existing server
    start_scp_server()  # Start a fresh server

    # Brief delay to ensure the SCP server is ready
    time.sleep(1)

    # Create an AE for Query/Retrieve operations
    ae = AE(ae_title="MY_CLIENT")
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)
    ae.add_requested_context(CTImageStorage)
    ae.add_requested_context(MRImageStorage)
    ae.add_requested_context(ComputedRadiographyImageStorage)
    for context in StoragePresentationContexts[:30]:
        ae.add_requested_context(context.abstract_syntax)

    logging.info("Associating with PACS...")
    assoc = ae.associate(PACS_IP, PACS_PORT, ae_title=PACS_AE_TITLE)

    if assoc.is_established:
        # Build and send a C-FIND query for the given PatientID
        query_ds = Dataset()
        query_ds.QueryRetrieveLevel = "PATIENT"
        query_ds.PatientID = patient_id

        logging.info("Sending C-FIND for PatientID: %s", patient_id)
        found = False

        try:
            responses = assoc.send_c_find(query_ds, PatientRootQueryRetrieveInformationModelFind)
            for status, identifier in responses:
                logging.debug("C-FIND Response: %s, Identifier: %s", status, identifier)
                if status and status.Status in (0xFF00, 0xFF01):
                    found = True
                    break

            if not found:
                assoc.release()
                stop_scp_server()
                return jsonify({'images': []})

            # Build and send a C-MOVE request to retrieve images
            move_ds = Dataset()
            move_ds.QueryRetrieveLevel = "PATIENT"
            move_ds.PatientID = patient_id

            logging.info("Sending C-MOVE for PatientID: %s to %s", patient_id, CLIENT_AE_TITLE)
            responses = assoc.send_c_move(
                move_ds,
                move_aet=CLIENT_AE_TITLE,
                query_model=PatientRootQueryRetrieveInformationModelMove
            )

            completed = False
            for status, identifier in responses:
                if status:
                    status_code = status.Status
                    logging.info("C-MOVE Response: Status 0x{0:04X}".format(status_code))
                    if status_code == 0x0000:
                        completed = True

            if not completed:
                logging.error("C-MOVE failed or was incomplete.")

        except Exception as e:
            logging.error("Error during DICOM operations: %s", str(e))
        finally:
            if assoc.is_established:
                assoc.release()
    else:
        return jsonify({'error': 'Could not associate with PACS'}), 500

    # Wait until the file count in the destination folder has stabilized
    folder = os.path.join("static", f"retrieved_{patient_id}")
    files = wait_for_files(folder)

    # Build full URLs using the request host information for all files
    for fname in files:
        full_url = request.host_url.rstrip('/') + f"/static/retrieved_{patient_id}/{fname}"
        image_urls.append(full_url)

    # Stop the SCP server after processing
    stop_scp_server()

    return jsonify({'images': image_urls})

if __name__ == "__main__":
    # Ensure the static folder exists
    os.makedirs("static", exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
