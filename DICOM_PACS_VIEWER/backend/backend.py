from flask import Flask, jsonify, send_file, request
from pynetdicom import AE, StoragePresentationContexts
from pynetdicom.sop_class import PatientRootQueryRetrieveInformationModelFind, PatientRootQueryRetrieveInformationModelMove, CTImageStorage
from pydicom.dataset import Dataset
import os

app = Flask(__name__)

# Configure your PACS connection details
PACS_AE_TITLE = "MYPACS"
PACS_IP = "127.0.0.1"
PACS_PORT = 104

# Define an endpoint to query images by PatientID
@app.route('/api/images', methods=['GET'])
def get_images():
    patient_id = request.args.get('patientId')
    if not patient_id:
        return jsonify({'error': 'PatientID is required'}), 400

    # Initialize AE for query/retrieve
    ae = AE(ae_title="MY_VIEWER")
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
    ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)
    ae.add_requested_context(CTImageStorage)
    
    assoc = ae.associate(PACS_IP, PACS_PORT, ae_title=PACS_AE_TITLE)
    image_urls = []
    if assoc.is_established:
        # Perform a C-FIND query to get the study information
        query_ds = Dataset()
        query_ds.QueryRetrieveLevel = "PATIENT"
        query_ds.PatientID = patient_id
        responses = assoc.send_c_find(query_ds, PatientRootQueryRetrieveInformationModelFind)
        found = False
        for status, identifier in responses:
            if status and status.Status == 0xFF00:
                found = True
                break
        if found:
            # Do a C-MOVE to retrieve the images (assume they are stored in a known folder)
            move_ds = Dataset()
            move_ds.QueryRetrieveLevel = "PATIENT"
            move_ds.PatientID = patient_id
            # Here, the 'move_aet' parameter is your backend’s receiving AE.
            responses = assoc.send_c_move(move_ds, move_aet="MY_BACKEND", 
                                          query_model=PatientRootQueryRetrieveInformationModelMove)
            # Wait for images to be saved in a known folder, then list them.
            # For example, assume images are saved in a folder named f"retrieved_{patient_id}".
            folder = f"retrieved_{patient_id}"
            if os.path.exists(folder):
                # Build URLs for each image file (assumes your server serves static files)
                for filename in os.listdir(folder):
                    if filename.endswith('.dcm'):
                        image_urls.append(f"/static/{folder}/{filename}")
        assoc.release()
    else:
        return jsonify({'error': 'Could not associate with PACS'}), 500

    return jsonify({'images': image_urls})

if __name__ == "__main__":
    # Make sure your static folder includes the retrieved images folder or configure accordingly
    app.run(host='0.0.0.0', port=5000)
