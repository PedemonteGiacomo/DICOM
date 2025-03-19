import os
import pydicom
import matplotlib.pyplot as plt
from pydicom.dataset import Dataset
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import CTImageStorage, PatientRootQueryRetrieveInformationModelFind, PatientRootQueryRetrieveInformationModelMove
import time

# Configuration
PACS_AE_TITLE = "MYPACS"
PACS_IP = "127.0.0.1"
PACS_PORT = 104
CLIENT_AE_TITLE = "TESTSCU"       # Must match the AE Title expected by the PACS
CLIENT_PORT = 11113               # Must correspond to the port configured in the PACS

# Create the Application Entity for the DICOM viewer
viewer_ae = AE(ae_title=CLIENT_AE_TITLE)
viewer_ae.supported_contexts = StoragePresentationContexts
viewer_ae.add_requested_context(CTImageStorage)
viewer_ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
viewer_ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)

# Handler to store received images in folder "retrieved_<PatientID>"
def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    # Retrieve the PatientID; use "unknown" if not present
    patient_id = ds.get("PatientID", "unknown")
    # Create the target folder (e.g., "retrieved_100_HM10395")
    folder_name = f"retrieved_{patient_id}"
    os.makedirs(folder_name, exist_ok=True)
    # Save the file inside the target folder
    filename = os.path.join(folder_name, f"retrieved_{ds.SOPInstanceUID}.dcm")
    ds.save_as(filename, write_like_original=False)
    print("Received and saved:", filename)
    return 0x0000  # Success status

# Start a server to receive images from the PACS
handlers = [(evt.EVT_C_STORE, handle_store)]
scp = viewer_ae.start_server(("0.0.0.0", CLIENT_PORT), block=False, evt_handlers=handlers)

# Step 1: Associate with the PACS for Query/Retrieve operations
assoc = viewer_ae.associate(PACS_IP, PACS_PORT, ae_title=PACS_AE_TITLE)

if assoc.is_established:
    print("Connected to PACS.")

    # Step 2: Perform a C-FIND query to search for PatientID "100_HM10395"
    query_ds = Dataset()
    query_ds.QueryRetrieveLevel = "PATIENT"
    query_ds.PatientID = "100_HM10395"

    found = False
    responses = assoc.send_c_find(query_ds, PatientRootQueryRetrieveInformationModelFind)
    for status, identifier in responses:
        if status and status.Status == 0xFF00:  # Pending status
            print("Found match:", identifier)
            found = True

    if found:
        # Step 3: Request the retrieval (C-MOVE) of images for the patient "100_HM10395"
        move_ds = Dataset()
        move_ds.QueryRetrieveLevel = "PATIENT"
        move_ds.PatientID = "100_HM10395"

        responses = assoc.send_c_move(move_ds, move_aet=CLIENT_AE_TITLE,
                                      query_model=PatientRootQueryRetrieveInformationModelMove)
        for status, identifier in responses:
            if status and status.Status in (0xFF00, 0x0000):
                print("C-MOVE Response: Status 0x{0:04X}".format(status.Status))
    else:
        print("No matching study found.")

    # Release the association after operations
    assoc.release()
else:
    print("Failed to associate with PACS.")

# Wait a moment for images to be received
time.sleep(2)

# Step 4: Load and display the first retrieved image
# Since images are saved in folder "retrieved_100_HM10395", we look there
target_folder = "retrieved_100_HM10395"
if os.path.exists(target_folder):
    retrieved_files = [os.path.join(target_folder, f) for f in os.listdir(target_folder) if f.endswith(".dcm")]
else:
    retrieved_files = []

if retrieved_files:
    dicom_file = retrieved_files[0]
    ds = pydicom.dcmread(dicom_file)
    # print(ds)
    print("Displaying image from", dicom_file)
    plt.imshow(ds.pixel_array, cmap="gray")
    plt.title("Patient: {}".format(ds.PatientName))
    plt.axis("off")
    plt.show()
else:
    print("No images retrieved.")

# Shutdown the SCP listener
scp.shutdown()
