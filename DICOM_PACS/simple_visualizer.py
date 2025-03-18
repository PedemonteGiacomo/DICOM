import sys
import numpy as np
import pydicom
from PyQt5.QtWidgets import QApplication, QGraphicsScene, QGraphicsView
from PyQt5.QtGui import QImage, QPixmap

class DICOMViewer(QGraphicsView):
    def __init__(self, dicom_path):
        super().__init__()
        # Load DICOM file
        ds = pydicom.dcmread(dicom_path)
        pixel_array = ds.pixel_array.astype(np.float32)  # get image data as float array

        # Apply window level (if available in dataset, otherwise use full range)
        if hasattr(ds, 'WindowCenter') and hasattr(ds, 'WindowWidth'):
            center = float(ds.WindowCenter); width = float(ds.WindowWidth)
        else:
            # default window: use min/max of data
            center = pixel_array.mean(); width = pixel_array.max() - pixel_array.min()
        # Compute windowed 8-bit image
        low = center - width/2.0
        high = center + width/2.0
        clipped = np.clip(pixel_array, low, high)
        # Scale to 0-255
        img8 = ((clipped - low) / (high - low) * 255.0).astype(np.uint8)

        # Create QImage from the 8-bit data
        height, width = img8.shape
        bytes_per_line = width  # since Format_Grayscale8, one byte per pixel
        qimg = QImage(img8.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg)

        # Set up QGraphicsView with the image
        scene = QGraphicsScene()
        scene.addPixmap(pixmap)
        self.setScene(scene)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setWindowTitle(f"DICOM Viewer - {dicom_path}")
        self.show()

    # Override wheelEvent for zooming
    def wheelEvent(self, event):
        zoom_in_factor = 1.25
        zoom_out_factor = 1/zoom_in_factor
        if event.angleDelta().y() > 0:
            self.scale(zoom_in_factor, zoom_in_factor)
        else:
            self.scale(zoom_out_factor, zoom_out_factor)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python visualizer.py <dicom_file_path>")
        sys.exit(1)
        
    app = QApplication(sys.argv)
    dicom_file = sys.argv[1]  # get file path from command line argument
    viewer = DICOMViewer(dicom_file)
    sys.exit(app.exec_())