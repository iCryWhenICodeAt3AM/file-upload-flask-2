import os
import json
import logging
from logging.handlers import RotatingFileHandler
import psycopg2

from flask import Flask, flash, request, redirect, url_for, render_template, send_from_directory, Response
from werkzeug.utils import secure_filename
from db.mongodb.mongodb_connection import create_mongodb_connection

# Configuration for file uploads
UPLOAD_FOLDER = os.getenv("UPLOAD_DIRECTORY")  # Directory where uploaded files will be stored
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}  # Allowed file extensions
ENV_MODE = os.getenv("ENV_MODE")  # Environment mode (e.g., "backend" for API-only responses)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configure logging with a rotating file handler
LOG_FILE = "app.log"
handler = RotatingFileHandler(LOG_FILE, maxBytes=10000, backupCount=1)  # Log rotation settings
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)  # Logger instance for the application

@app.route("/")
def hello_world():

    """Simple route to test if the application is running."""
    logger.info("Accessed the home page.")

    return "<p>Hello, World Elisha!</p>"

def allowed_file(filename):
    """
    Check if the uploaded file has an allowed extension.
    :param filename: Name of the uploaded file
    :return: True if the file extension is allowed, False otherwise
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload-file', methods=['GET', 'POST'])
def upload_file():
    """
    Handle file uploads. Supports both GET and POST methods.
    - GET: Render the upload form.
    - POST: Process the uploaded file, save it, and log the result.
    """
    logger.info("Accessed the upload file page.")
    if request.method == 'POST':
        try:
            logger.info("Received a POST request to upload a file.")

            # Check for forced failure (triggered by a button in the form)
            if request.form.get('force_failure') == 'true':
                raise Exception("Forced failure triggered.")

            # Check if the file part exists in the request
            if 'file' not in request.files:
                logger.error("Failed: No file part in the request.")
                flash('No file part')
                return redirect(request.url)

            file = request.files['file']

            # Check if a file was selected
            if file.filename == '':
                logger.error("Failed: No file selected for upload.")
                flash('No selected file')
                return redirect(request.url)

            # Validate the file and save it
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)  # Sanitize the filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)  # Save the file to the upload directory

                # MongoDB operations: Save file metadata
                client, database, collection = create_mongodb_connection("file-uploads")
                result = collection.insert_one({"file_path": filename})
                client.close()

                # PostgreSQL operations: Save product details
                conn = psycopg2.connect(
                    host=os.environ["POSTGRESQL_DB_HOST"],
                    database=os.environ["POSTGRESQL_DB_DATABASE_NAME"],
                    user=os.environ['POSTGRESQL_DB_USERNAME'],
                    password=os.environ['POSTGRESQL_DB_PASSWORD']
                )
                cur = conn.cursor()
                product_name = request.form.get('product_name')  # Product name from the form
                image_mongodb_id = str(result.inserted_id)  # MongoDB ID of the uploaded file
                stock_count = int(request.form.get('initial_stock_count'))  # Initial stock count
                review = "Sample Review"  # Placeholder review

                # Insert product details into the PostgreSQL database
                cur.execute('INSERT INTO products (name, image_mongodb_id, stock_count, review)'
                            'VALUES (%s, %s, %s, %s)',
                            (product_name, image_mongodb_id, stock_count, review))
                conn.commit()
                cur.close()
                conn.close()

                # Generate the URL for the uploaded file
                img_url = url_for('download_file', name=filename)

                # Log success only if all operations complete successfully
                logger.info("Success: File upload completed successfully.")
                if ENV_MODE == "backend":
                    return {"filename": filename, "img_url": img_url}  # Return JSON response in backend mode
                else:
                    # Render an HTML page showing the uploaded file
                    return f'''
                    <!doctype html>
                    <html>
                        <h1>{filename}</h1>
                        <img src={img_url}></img>
                    </html>
                    '''
        except Exception as e:
            # Log failure if any part of the process fails
            logger.error(f"Failed: {str(e)}")
            flash(f"An error occurred: {str(e)}")
            return redirect(request.url)

    # Render the upload form for GET requests
    return render_template('upload_image.html')

@app.route('/images', methods=['GET'])
def show_uploaded_images():
    """
    Display a list of uploaded images.
    - In backend mode, return a JSON response with image URLs.
    - In frontend mode, render an HTML page with image links.
    """
    logger.info("Accessed the images page.")
    client, database, collection = create_mongodb_connection("file-uploads")
    data = list(collection.find({}))  # Fetch all uploaded file metadata from MongoDB
    logger.info(f"Fetched {len(data)} images from MongoDB.")
    parsed = [{"image_url": url_for('download_file', name=d['file_path'])} for d in data]

    if ENV_MODE == "backend":
        return json.dumps({"data": parsed})  # Return JSON response in backend mode
    else:
        return render_template('view_images.html', navigation=parsed)  # Render HTML page in frontend mode

@app.route('/uploads/<name>')
def download_file(name):
    """
    Serve a file from the upload directory.
    :param name: Name of the file to be downloaded
    :return: File response
    """
    logger.info(f"File {name} requested for download.")
    return send_from_directory(app.config["UPLOAD_FOLDER"], name)

@app.route('/logs', methods=['GET'])
def watch_logs():
    """
    Stream the log file in real-time.
    - Useful for debugging or monitoring application logs.
    """
    def generate():
        with open(LOG_FILE, "r") as f:
            while True:
                line = f.readline()
                if not line:
                    break
                yield line
    return Response(generate(), mimetype="text/plain")
