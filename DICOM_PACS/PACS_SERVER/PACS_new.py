# PACS (pacs.py)
from pynetdicom import AE, evt, StoragePresentationContexts, debug_logger
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    CTImageStorage, MRImageStorage, ComputedRadiographyImageStorage
)
from pydicom.dataset import Dataset
import logging
import os

# Enable debug logging
debug_logger()
logging.basicConfig(level=logging.DEBUG)

# Configuration constants
PACS_AE_TITLE = "MYPACS"
PACS_PORT = 104

# In-memory list of stored datasets
stored_datasets = []

# C-STORE handler: save incoming DICOM and index it
def handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    filename = ds.SOPInstanceUID + ".dcm"
    ds.save_as(filename, write_like_original=False)
    logging.info("Stored DICOM: %s", filename)
    stored_datasets.append(ds)
    return 0x0000

# C-FIND handler: return matching datasets based on PatientID
def handle_find(event):
    ds = event.identifier
    level = ds.QueryRetrieveLevel
    matches = []

    if level == "PATIENT" and 'PatientID' in ds and ds.PatientID:
        patient_ids_seen = set()

        for inst in stored_datasets:
            if (hasattr(inst, 'PatientID') and
                    inst.PatientID.strip() == ds.PatientID.strip() and
                    inst.PatientID not in patient_ids_seen):

                patient_ids_seen.add(inst.PatientID)
                res = Dataset()
                res.QueryRetrieveLevel = "PATIENT"
                res.PatientID = inst.PatientID
                if hasattr(inst, 'PatientName'):
                    res.PatientName = inst.PatientName
                matches.append(res)

    for match in matches:
        if event.is_cancelled:
            yield (0xFE00, None)
            return
        yield (0xFF00, match)

# C-MOVE handler: send matching datasets to the destination AE
def handle_move(event):
    ds = event.identifier
    dest_ae = event.move_destination

    # Ensure the destination is known
    KNOWN_AE_DESTINATIONS = {
        "TESTSCU": ("127.0.0.1", 11113),
        "TESTSCU2": ("127.0.0.1", 11119),  # Corrected AE Title
    }

    if dest_ae not in KNOWN_AE_DESTINATIONS:
        logging.error(f"Unknown move destination: {dest_ae}")
        yield (0xA801, None)  # Move destination unknown
        return

    addr, port = KNOWN_AE_DESTINATIONS[dest_ae]
    logging.info(f"Move destination: {dest_ae} at {addr}:{port}")

    # --- Modification Start ---
    # Create a temporary AE to collect requested presentation contexts
    temp_ae = AE()
    temp_ae.add_requested_context(CTImageStorage)
    temp_ae.add_requested_context(MRImageStorage)
    temp_ae.add_requested_context(ComputedRadiographyImageStorage)
    # Optionally, add additional storage contexts if needed:
    for context in StoragePresentationContexts[:50]:
        temp_ae.add_requested_context(context.abstract_syntax)
    # Yield a 3-tuple: destination address, port, and extra kwargs containing
    # the destination AE title and the list of requested presentation contexts.
    yield (addr, port, {"ae_title": dest_ae, "contexts": temp_ae.requested_contexts})
    # --- Modification End ---

    level = ds.QueryRetrieveLevel
    to_send = []

    if level == "PATIENT" and 'PatientID' in ds:
        for inst in stored_datasets:
            if hasattr(inst, 'PatientID') and inst.PatientID.strip() == ds.PatientID.strip():
                to_send.append(inst)

    logging.info(f"Found {len(to_send)} datasets to send")
    # Yield the number of datasets to be sent
    yield len(to_send)

    # Send each matching dataset through a new association
    for inst in to_send:
        if event.is_cancelled:
            yield (0xFE00, None)
            return

        # Create a storage SCU for sending images
        storage_ae = AE(ae_title=PACS_AE_TITLE)
        storage_ae.add_requested_context(CTImageStorage)
        storage_ae.add_requested_context(MRImageStorage)
        storage_ae.add_requested_context(ComputedRadiographyImageStorage)
        if hasattr(inst, 'SOPClassUID'):
            storage_ae.add_requested_context(inst.SOPClassUID)

        # Associate with the destination
        assoc = storage_ae.associate(addr, port, ae_title=dest_ae)
        if assoc.is_established:
            # Send the instance
            status = assoc.send_c_store(inst)
            assoc.release()

            if status and status.Status == 0x0000:
                logging.info(f"Successfully sent instance {inst.SOPInstanceUID}")
                yield (0xFF00, None)  # Success
            else:
                logging.error(f"Failed to send instance {inst.SOPInstanceUID}, status: {status}")
                yield (0xB000, None)  # Failed
        else:
            logging.error(f"Failed to establish association with {dest_ae} at {addr}:{port}")
            yield (0xA801, None)  # Move destination unavailable

# Set up PACS AE
ae = AE(ae_title=PACS_AE_TITLE)
# Add supported contexts with explicit role negotiation
ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind, scp_role=True, scu_role=False)
ae.add_supported_context(PatientRootQueryRetrieveInformationModelMove, scp_role=True, scu_role=False)

# Add storage contexts explicitly
for context in StoragePresentationContexts[:50]:
    ae.add_supported_context(context.abstract_syntax, scp_role=True, scu_role=True)

handlers = [
    (evt.EVT_C_STORE, handle_store),
    (evt.EVT_C_FIND, handle_find),
    (evt.EVT_C_MOVE, handle_move)
]

logging.info("🚀 PACS Server (%s) is starting on port %d...", PACS_AE_TITLE, PACS_PORT)
ae.start_server(("0.0.0.0", PACS_PORT), evt_handlers=handlers)
logging.info("✅ PACS Server is running and ready to receive DICOM files!")
