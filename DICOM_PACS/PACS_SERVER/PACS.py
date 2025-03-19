# from pynetdicom import AE, evt, AllStoragePresentationContexts
# from pynetdicom.sop_class import PatientRootQueryRetrieveInformationModelFind, PatientRootQueryRetrieveInformationModelMove
# from pydicom.dataset import Dataset

from pynetdicom import AE, evt, StoragePresentationContexts
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    CTImageStorage, MRImageStorage, ComputedRadiographyImageStorage  
)
from pydicom.dataset import Dataset
from pynetdicom.presentation import build_context

# In-memory list of stored datasets (populated in handle_store for simplicity)
stored_datasets = []

# Modify the C-STORE handler to index stored files (for query retrieval use)
def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    # Save file to disk
    filename = ds.SOPInstanceUID + ".dcm"
    ds.save_as(filename, write_like_original=False)
    print(f"Stored DICOM: {filename}")
    # Index the dataset for querying
    stored_datasets.append(ds)
    return 0x0000

# C-FIND handler (Query)
def handle_find(event):
    """Handle a C-FIND (query) request."""
    ds = event.identifier  # the query dataset
    level = ds.QueryRetrieveLevel
    matches = []
    # Simple matching logic based on level
    if level == "PATIENT":
        # Match by Patient ID (if provided)
        if 'PatientID' in ds and ds.PatientID:
            for inst in stored_datasets:
                if hasattr(inst, 'PatientID') and inst.PatientID == ds.PatientID:
                    # Found a match; prepare patient-level response
                    res = Dataset()
                    res.QueryRetrieveLevel = "PATIENT"
                    res.PatientID = inst.PatientID
                    if hasattr(inst, 'PatientName'):
                        res.PatientName = inst.PatientName
                    matches.append(res)
    elif level == "STUDY":
        if 'StudyInstanceUID' in ds and ds.StudyInstanceUID:
            for inst in stored_datasets:
                if hasattr(inst, 'StudyInstanceUID') and inst.StudyInstanceUID == ds.StudyInstanceUID:
                    # Prepare study-level response (including PatientID and Study UID)
                    res = Dataset()
                    res.QueryRetrieveLevel = "STUDY"
                    res.PatientID = getattr(inst, 'PatientID', '')
                    res.StudyInstanceUID = inst.StudyInstanceUID
                    res.StudyDescription = getattr(inst, 'StudyDescription', '')
                    matches.append(res)
                    break  # one study match is enough
    elif level == "SERIES":
        if 'SeriesInstanceUID' in ds and ds.SeriesInstanceUID:
            for inst in stored_datasets:
                if hasattr(inst, 'SeriesInstanceUID') and inst.SeriesInstanceUID == ds.SeriesInstanceUID:
                    # Prepare series-level response
                    res = Dataset()
                    res.QueryRetrieveLevel = "SERIES"
                    res.PatientID = getattr(inst, 'PatientID', '')
                    res.StudyInstanceUID = getattr(inst, 'StudyInstanceUID', '')
                    res.SeriesInstanceUID = inst.SeriesInstanceUID
                    res.Modality = getattr(inst, 'Modality', '')
                    matches.append(res)
                    break
    else:
        # Unsupported level
        yield (0xC000, None)  # Failure status
        return

    # Yield all matching results as pending
    for match in matches:
        if event.is_cancelled:
            yield (0xFE00, None)  # Cancel status
            return
        yield (0xFF00, match)
    # After yielding matches, the framework will send a final Success (0x0000) by default

# Known AE titles and their network addresses for C-MOVE
# (Key: AE Title, Value: (IP, Port))
KNOWN_AE_DESTINATIONS = {
    "TESTSCU": ("127.0.0.1", 11113),  # e.g., our test client AE
    "TESTSCU2": ("127.0.0.1", 11119)  # additional test client AE
}

# C-MOVE handler (Retrieve)
def handle_move(event):
    """Handle a C-MOVE request to send images to a remote AE."""
    ds = event.identifier  # the query dataset (similar to C-FIND criteria)
    dest_ae = event.move_destination  # destination AE title where images should be sent
    # Lookup the destination AE info
    if dest_ae not in KNOWN_AE_DESTINATIONS:
        yield (0xA801, None)  # Unknown Move Destination (refused)&#8203;:contentReference[oaicite:12]{index=12}
        return
    addr, port = KNOWN_AE_DESTINATIONS[dest_ae]
    yield (addr, port)  # Provide address and port for the association to the destination

    # Find matching instances to send (for simplicity, reuse logic from handle_find)
    level = ds.QueryRetrieveLevel
    to_send = []
    if level == "PATIENT" and 'PatientID' in ds:
        to_send = [inst for inst in stored_datasets if hasattr(inst, 'PatientID') and inst.PatientID == ds.PatientID]
    elif level == "STUDY" and 'StudyInstanceUID' in ds:
        to_send = [inst for inst in stored_datasets if hasattr(inst, 'StudyInstanceUID') and inst.StudyInstanceUID == ds.StudyInstanceUID]
    elif level == "SERIES" and 'SeriesInstanceUID' in ds:
        to_send = [inst for inst in stored_datasets if hasattr(inst, 'SeriesInstanceUID') and inst.SeriesInstanceUID == ds.SeriesInstanceUID]
    # Yield number of sub-operations (number of C-STOREs to perform)
    yield len(to_send)
    # Send each matching dataset
    for inst in to_send:
        if event.is_cancelled:
            yield (0xFE00, None)  # if client sent C-CANCEL
            return
        # Yield each instance as a pending store operation
        yield (0xFF00, inst)
    # Pynetdicom will handle sending these instances via C-STORE to the destination AE.

# Set up the Application Entity (AE) for the PACS server
ae = AE(ae_title="MYPACS")

# Only support necessary storage contexts (e.g., CT, MR, CR)
ae.supported_contexts = StoragePresentationContexts[:50]  # Keep it within 128

# Query/Retrieve SOP Classes
ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind)
ae.add_supported_context(PatientRootQueryRetrieveInformationModelMove)

# Request only the necessary storage SOP classes for sending images
ae.requested_contexts = [
    build_context(CTImageStorage),
    build_context(MRImageStorage),
    build_context(ComputedRadiographyImageStorage)  # Add only essential modalities to avoid exceeding 128
]

handlers = [
    (evt.EVT_C_STORE, handle_store),
    (evt.EVT_C_FIND, handle_find),
    (evt.EVT_C_MOVE, handle_move)
]

# Console log before starting the PACS server
print("🚀 PACS Server (MYPACS) is starting on port 104...")

# Start the PACS server
ae.start_server(("0.0.0.0", 104), evt_handlers=handlers)

# Console log to confirm the server has started
print("✅ PACS Server is running and ready to receive DICOM files!")
