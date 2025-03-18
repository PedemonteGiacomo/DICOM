from flask import Flask, request, jsonify, send_file, abort
import os
import io
import glob
import zipfile
import requests
import pydicom
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas

app = Flask(__name__)

BASE_URL = "https://services.cancerimagingarchive.net/services/v4/TCIA/query"

@app.route("/collections", methods=["GET"])
def get_collections():
    url = f"{BASE_URL}/getCollectionValues"
    response = requests.get(url)
    if response.status_code == 200:
        collections = response.json()
        return jsonify(collections)
    else:
        return jsonify({"error": "Failed to retrieve collections"}), response.status_code

@app.route("/patients", methods=["GET"])
def get_patients():
    # Expecting a collection name as query param: /patients?collection=XYZ
    collection = request.args.get("collection")
    if not collection:
        return jsonify({"error": "Missing 'collection' parameter"}), 400
    
    url = f"{BASE_URL}/getPatient?Collection={collection}"
    response = requests.get(url)
    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify({"error": "Failed to retrieve patients"}), response.status_code

@app.route("/studies", methods=["GET"])
def get_studies():
    # /studies?collection=XYZ&patient_id=ABC
    collection = request.args.get("collection")
    patient_id = request.args.get("patient_id")

    if not collection or not patient_id:
        return jsonify({"error": "Missing 'collection' or 'patient_id'"}), 400
    
    url = f"{BASE_URL}/getPatientStudy?Collection={collection}&PatientID={patient_id}"
    response = requests.get(url)
    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify({"error": "Failed to retrieve studies"}), response.status_code

@app.route("/series", methods=["GET"])
def get_series():
    # /series?collection=XYZ&patient_id=ABC&study_uid=DEF
    collection = request.args.get("collection")
    patient_id = request.args.get("patient_id")
    study_instance_uid = request.args.get("study_uid")

    if not collection or not patient_id or not study_instance_uid:
        return jsonify({"error": "Missing required params"}), 400
    
    url = (f"{BASE_URL}/getSeries?"
           f"Collection={collection}&PatientID={patient_id}&StudyInstanceUID={study_instance_uid}")
    response = requests.get(url)
    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify({"error": "Failed to retrieve series"}), response.status_code

@app.route("/download-series", methods=["GET"])
def download_series():
    # /download-series?series_uid=123
    series_instance_uid = request.args.get("series_uid")
    if not series_instance_uid:
        return jsonify({"error": "Missing 'series_uid'"}), 400
    
    output_dir = "dicom_images"
    os.makedirs(output_dir, exist_ok=True)

    # Download from API
    url = f"{BASE_URL}/getImage?SeriesInstanceUID={series_instance_uid}"
    response = requests.get(url)
    if response.status_code != 200:
        return jsonify({"error": "Failed to download series"}), response.status_code

    # Extract the ZIP to dicom_images/
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        z.extractall(output_dir)

    return jsonify({"message": f"Series {series_instance_uid} downloaded to {output_dir}."})

@app.route("/dicom-preview", methods=["GET"])
def dicom_preview():
    """Return a PNG preview of the first DICOM file in the output_dir."""
    output_dir = "dicom_images"
    dicom_files = glob.glob(os.path.join(output_dir, "*.dcm"))
    if not dicom_files:
        return jsonify({"error": "No DICOM files found"}), 404

    # Read first file
    ds = pydicom.dcmread(dicom_files[0])
    if 'PixelData' not in ds:
        return jsonify({"error": "No pixel data found in DICOM"}), 400

    # Convert to a PNG and return it
    fig = plt.figure(figsize=(6,6))
    plt.imshow(ds.pixel_array, cmap='gray')
    plt.axis('off')

    png_image = io.BytesIO()
    FigureCanvas(fig).print_png(png_image)
    plt.close(fig)
    png_image.seek(0)
    
    return send_file(png_image, mimetype='image/png')

@app.route("/dicom-metadata", methods=["GET"])
def dicom_metadata():
    """Return DICOM metadata (for the first file) as JSON."""
    output_dir = "dicom_images"
    dicom_files = glob.glob(os.path.join(output_dir, "*.dcm"))
    if not dicom_files:
        return jsonify({"error": "No DICOM files found"}), 404

    ds = pydicom.dcmread(dicom_files[0])

    # Return the metadata in a structured format (tag -> value)
    # Keep in mind some data might be nested sequences or private tags
    metadata_dict = {}
    for elem in ds:
        # Convert each DataElement to a more readable form
        if elem.VR == 'SQ':  
            # Sequences can be quite complex; handle as you need
            metadata_dict[elem.name] = "Sequence (not fully expanded)"
        else:
            metadata_dict[elem.name] = str(elem.value)

    return jsonify(metadata_dict)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
