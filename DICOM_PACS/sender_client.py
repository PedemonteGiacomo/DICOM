import os
import pydicom
import shutil
from pynetdicom import AE, StoragePresentationContexts
from pynetdicom.sop_class import CTImageStorage  # Aggiungi altri Storage SOP se necessario

# Configurazione PACS
PACS_AE_TITLE = "MYPACS"
PACS_IP = "127.0.0.1"
PACS_PORT = 104

# Cartelle
DICOM_FOLDER = "dicom_images"  # Cartella con i file DICOM da inviare
SENDED_FOLDER = "sended"       # Cartella in cui spostare i file inviati

# Crea la cartella "sended" se non esiste già
os.makedirs(SENDED_FOLDER, exist_ok=True)

# Crea l'Application Entity per il sender
ae = AE(ae_title="SENDER")
ae.supported_contexts = StoragePresentationContexts
ae.add_requested_context(CTImageStorage)
# Se necessario, aggiungi altri contesti per altri modali (es. MRImageStorage, etc.)

# Associa al PACS
assoc = ae.associate(PACS_IP, PACS_PORT, ae_title=PACS_AE_TITLE)

if assoc.is_established:
    print("Association with PACS established.")
    
    # Itera tutti i file nella cartella e invia quelli con estensione .dcm
    for file in os.listdir(DICOM_FOLDER):
        if file.lower().endswith(".dcm"):
            file_path = os.path.join(DICOM_FOLDER, file)
            try:
                ds = pydicom.dcmread(file_path)
                print(f"Sending {file_path}...")
                status = assoc.send_c_store(ds)
                if status and status.Status == 0x0000:
                    print(f"C-STORE successful: {file_path}")
                    # Sposta il file inviato nella cartella "sended"
                    new_path = os.path.join(SENDED_FOLDER, file)
                    shutil.move(file_path, new_path)
                    print(f"Moved {file_path} to {new_path}")
                else:
                    print(f"C-STORE failed for {file_path} with status 0x{status.Status:04X}")
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
    
    # Rilascia l'associazione
    assoc.release()
    print("Association released.")
else:
    print("Failed to associate with PACS.")
