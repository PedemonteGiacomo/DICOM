import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian
from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import CTImageStorage, PatientRootQueryRetrieveInformationModelFind, PatientRootQueryRetrieveInformationModelMove

# Step 1: Generate a test DICOM dataset
file_meta = Dataset()
file_meta.MediaStorageSOPClassUID = CTImageStorage  # SOP Class UID for CT Image
file_meta.MediaStorageSOPInstanceUID = generate_uid()
file_meta.ImplementationClassUID = generate_uid()
file_meta.TransferSyntaxUID = ExplicitVRLittleEndian  # FIXED: Add Transfer Syntax UID

# Create the FileDataset with required meta fields
ds = FileDataset("TestCT", {}, file_meta=file_meta, preamble=b"\x00" * 128)

# Add required attributes
ds.SOPClassUID = CTImageStorage
ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
ds.PatientID = "TEST001"
ds.PatientName = "Test^Patient"
ds.StudyInstanceUID = generate_uid()
ds.SeriesInstanceUID = generate_uid()
ds.Modality = "CT"
ds.Rows = 128
ds.Columns = 128
ds.BitsAllocated = 16
ds.BitsStored = 16
ds.HighBit = 15
ds.PixelRepresentation = 0  # unsigned
ds.SamplesPerPixel = 1
ds.PhotometricInterpretation = "MONOCHROME2"

# Create a random image and set PixelData
pixel_data = (np.random.rand(ds.Rows, ds.Columns) * 65535).astype(np.uint16)
ds.PixelData = pixel_data.tobytes()

# Step 2: Setup client AE and its SCP to receive C-MOVE results
client_ae = AE(ae_title="TESTSCU")
client_ae.supported_contexts = StoragePresentationContexts
client_ae.add_requested_context(CTImageStorage)  # for C-STORE SCU
client_ae.add_requested_context(PatientRootQueryRetrieveInformationModelFind)
client_ae.add_requested_context(PatientRootQueryRetrieveInformationModelMove)

# Define handler to receive images from C-MOVE (as a Storage SCP)
def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    filename = "received_" + ds.SOPInstanceUID + ".dcm"
    ds.save_as(filename, write_like_original=False)
    print(f"Received image from server and saved as {filename}")
    return 0x0000

handlers = [(evt.EVT_C_STORE, handle_store)]

# Start a listener in the background for incoming C-STORE (from C-MOVE operations)
scp = client_ae.start_server(("0.0.0.0", 11113), block=False, evt_handlers=handlers)

# Step 3: Associate with PACS server (acting as SCU)
assoc = client_ae.associate("127.0.0.1", 104, ae_title="MYPACS")
if assoc.is_established:
    print("Association with PACS established.")

    # Step 3a: Send the DICOM image to PACS (C-STORE)
    status = assoc.send_c_store(ds)
    if status and status.Status == 0x0000:
        print("C-STORE successful: Image sent to PACS server.")
    else:
        print("C-STORE failed or timed out.")

    # Step 3b: Query the PACS for the patient (C-FIND)
    query_ds = Dataset()
    query_ds.QueryRetrieveLevel = "PATIENT"
    query_ds.PatientID = "TEST001"
    responses = assoc.send_c_find(query_ds, PatientRootQueryRetrieveInformationModelFind)
    for (status, identifier) in responses:
        if status.Status == 0xFF00:
            print("C-FIND match found:", identifier)

    # Step 3c: Retrieve the image back from PACS (C-MOVE)
    # move_ds = Dataset()
    # move_ds.QueryRetrieveLevel = "PATIENT"
    # move_ds.PatientID = "TEST001"
    # responses = assoc.send_c_move(move_ds, move_aet="TESTSCU",  # FIXED: `move_aet` instead of `destination`
    #                               query_model=PatientRootQueryRetrieveInformationModelMove)
    # for (status, identifier) in responses:
    #     if status and status.Status in (0xFF00, 0x0000):
    #         print(f"C-MOVE response status: 0x{status.Status:04X}")

    # Release association after operations
    assoc.release()
else:
    print("Failed to associate with PACS server.")

# Stop the client SCP listener
scp.shutdown()
