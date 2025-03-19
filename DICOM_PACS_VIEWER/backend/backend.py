from flask import Flask, jsonify, request
from flask_cors import CORS
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    CTImageStorage
)
from pydicom.dataset import Dataset
import os
import threading
import time

app = Flask(__name__)
CORS(app)

# PACS connection details
PACS_AE_TITLE = "MYPACS"
PACS_IP = "127.0.0.1"
PACS_PORT = 104

# Client AE details (for receiving images)
CLIENT_AE_TITLE = "TESTSCU2"
CLIENT_PORT = 11119

# C-STORE handler to store received images in folder "retrieved_<PatientID>"
def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    patient_id = ds.get("PatientID", "unknown")
    folder_name = f"retrieved_{patient_id}"
    os.makedirs(folder_name, exist_ok=True)
    filename = os.path.join(folder_name, f"retrieved_{ds.SOPInstanceUID}.dcm")
    ds.save_as(filename, write_like_original=False)
    print("Received and saved:", filename)
    return 0x0000  # Success

# Function to start the DICOM C-STORE SCP server
def start_dicom_server():
    ae = AE(ae_title=CLIENT_AE_TITLE)
    ae.supported_contexts = StoragePresentationContexts
    ae.add_requested_context(CTImageStorage)
    handlers = [(evt.EVT_C_STORE, handle_store)]
    # Start the server; block=True makes it run continuously
    ae.start_server(("0.0.0.0", CLIENT_PORT), block=False, evt_handlers=handlers)

def stop_dicom_server():
    ae = AE(ae_title=CLIENT_AE_TITLE)
    ae.shotdown()

# Start the SCP server in a separate daemon thread
server_thread = threading.Thread(target=start_dicom_server, daemon=True)
server_thread.start()

@app.route('/api/images', methods=['GET'])
def get_images():
    patient_id = request.args.get('patientId')
    if not patient_id:
        return jsonify({'error': 'PatientID is required'}), 400

    # Create an AE for Query/Retrieve operations
    ae = AE(ae_title="MY_CLIENT")
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)
    ae.add_requested_context(CTImageStorage)

    # Associate with the PACS
    assoc = ae.associate(PACS_IP, PACS_PORT, ae_title=PACS_AE_TITLE)
    image_urls = []

    if assoc.is_established:
        # Perform a C-FIND query for the patient
        query_ds = Dataset()
        query_ds.QueryRetrieveLevel = "PATIENT"
        query_ds.PatientID = patient_id
        print(query_ds)
        found = False

        responses = assoc.send_c_find(query_ds, PatientRootQueryRetrieveInformationModelFind)
        for status, identifier in responses:
            if status and status.Status == 0xFF00:  # Pending status indicates a match
                found = True
                break

        if found:
            # Issue a C-MOVE to retrieve the images, directing them to our SCP (move_aet)
            move_ds = Dataset()
            move_ds.QueryRetrieveLevel = "PATIENT"
            move_ds.PatientID = patient_id
            print(move_ds)
            responses = assoc.send_c_move(
                move_ds, move_aet=CLIENT_AE_TITLE,
                query_model=PatientRootQueryRetrieveInformationModelMove
            )
            for status, identifier in responses:
                print("C-MOVE Response Status:", hex(status.Status) if status else "No status")
            # Wait briefly to allow images to be received via C-STORE
            time.sleep(2)  # Adjust delay as needed
            folder = f"retrieved_{patient_id}"
            if os.path.exists(folder):
                for filename in os.listdir(folder):
                    if filename.endswith('.dcm'):
                        image_urls.append(f"/static/{folder}/{filename}")
        assoc.release()
    else:
        return jsonify({'error': 'Could not associate with PACS'}), 500

    return jsonify({'images': image_urls})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
