import os
import json
import re
from flask import Flask, render_template, request, flash, redirect, url_for
from werkzeug.utils import secure_filename
import PyPDF2
import google.generativeai as genai
import logging

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2')  # Use env var for security
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure upload folder exists
print("Creating upload folder if it doesn't exist")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configure Gemini API
GEMINI_API_KEY = "AIzaSyDA7rPqm05AKhgUfwCWFCRd8bnWTtoEPQA"
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY environment variable is missing")
    print("ERROR: GEMINI_API_KEY environment variable is missing")
    raise ValueError("GEMINI_API_KEY environment variable is required")

print("Configuring Gemini API with provided key")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename):
    print(f"Checking if file {filename} is allowed")
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    print(f"Extracting text from PDF: {file_path}")
    text = ""
    try:
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            print(f"PDF has {len(pdf_reader.pages)} pages")
            for page_num, page in enumerate(pdf_reader.pages, 1):
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
                    print(f"Extracted text from page {page_num}")
                else:
                    logger.warning(f"Empty text extracted from page {page_num}")
                    print(f"WARNING: Empty text extracted from page {page_num}")
            if not text.strip():
                logger.warning("No text extracted from PDF")
                print("WARNING: No readable text extracted from PDF")
                return "No readable text found in the PDF."
    except Exception as e:
        logger.error(f"Error extracting PDF: {str(e)}")
        print(f"ERROR: Failed to extract PDF text: {str(e)}")
        return f"Error extracting text from PDF: {str(e)}"
    print("PDF text extraction completed")
    return text

def clean_json_response(response_text):
    """Remove Markdown code block wrappers from the response."""
    print(f"Cleaning response: {response_text[:100]}...")  # Log first 100 chars
    # Remove ```json and ```, accounting for whitespace
    cleaned = re.sub(r'```json\s*|\s*```', '', response_text.strip())
    print(f"Cleaned response: {cleaned[:100]}...")  # Log cleaned response
    return cleaned

@app.route('/')
def index():
    print("Rendering index page")
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_resume():
    print("Received upload request")
    if 'resume' not in request.files:
        flash('No file part')
        logger.warning("No file part in request")
        print("WARNING: No file part in request")
        return redirect(request.url)
    
    file = request.files['resume']
    if file.filename == '':
        flash('No selected file')
        logger.warning("No file selected")
        print("WARNING: No file selected")
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.normpath(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        print(f"Saving file to: {file_path}")
        try:
            file.save(file_path)
            logger.info(f"Saved uploaded file: {filename}")
            print(f"Saved file: {filename}")
            
            # Extract text
            resume_text = extract_text_from_pdf(file_path)
            print(f"Extracted resume text length: {len(resume_text)} characters")
            
            if "Error" in resume_text or "No readable text" in resume_text:
                flash(resume_text)
                logger.error(f"PDF extraction failed: {resume_text}")
                print(f"ERROR: PDF extraction failed: {resume_text}")
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Deleted file: {file_path}")
                return redirect(url_for('index'))
            
            # Generate ATS score using Gemini
            print("Sending prompt to Gemini API")
            prompt = f"""
            Analyze this resume for ATS (Applicant Tracking System) compatibility. 
            Provide an ATS score out of 100 based on:
            - Keyword optimization
            - Formatting and structure
            - Readability
            - Use of standard sections (e.g., Experience, Skills, Education)
            - Avoidance of tables/graphics that ATS might not parse well
            
            Resume content:
            {resume_text}
            
            Return a JSON object in this exact format:
            ```json
            {{
                "ats_score": <integer>,
                "feedback": "<string>"
            }}
            ```
            Ensure the response is valid JSON and contains only the specified fields. Do not wrap the JSON in Markdown code blocks or include extra text.
            """
            
            try:
                response = model.generate_content(prompt)
                logger.debug(f"Gemini API response: {response.text}")
                print(f"Gemini API response: {response.text}")
                
                # Validate and parse response
                if not response.text.strip():
                    logger.error("Empty response from Gemini API")
                    print("ERROR: Empty response from Gemini API")
                    flash("Error: Empty response from ATS analysis.")
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"Deleted file: {file_path}")
                    return redirect(url_for('index'))
                
                try:
                    # Clean the response to remove Markdown wrappers
                    cleaned_response = clean_json_response(response.text)
                    result = json.loads(cleaned_response)
                    ats_score = result.get('ats_score', 0)
                    feedback = result.get('feedback', 'No feedback available.')
                    print(f"Parsed ATS score: {ats_score}, Feedback: {feedback}")
                    
                    if not isinstance(ats_score, int) or not isinstance(feedback, str):
                        logger.error(f"Invalid response format: {result}")
                        print(f"ERROR: Invalid response format: {result}")
                        flash("Error: Invalid response format from ATS analysis.")
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            print(f"Deleted file: {file_path}")
                        return redirect(url_for('index'))
                    
                    logger.info(f"ATS Score: {ats_score}, Feedback: {feedback}")
                    print(f"Success: ATS Score: {ats_score}, Feedback: {feedback}")
                    
                    # Render template with error handling
                    try:
                        rendered = render_template('result.html', score=ats_score, feedback=feedback)
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            print(f"Deleted file: {file_path}")
                        return rendered
                    except Exception as e:
                        logger.error(f"Error rendering result.html: {str(e)}")
                        print(f"ERROR: Failed to render result.html: {str(e)}")
                        flash(f"Error rendering results: {str(e)}")
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            print(f"Deleted file: {file_path}")
                        return redirect(url_for('index'))
                
                except json.JSONDecodeError as json_err:
                    logger.error(f"JSON decode error: {str(json_err)}, Response: {response.text}")
                    print(f"ERROR: JSON decode error: {str(json_err)}, Response: {response.text}")
                    flash("Error: Invalid response from ATS analysis.")
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        print(f"Deleted file: {file_path}")
                    return redirect(url_for('index'))
            
            except Exception as e:
                logger.error(f"Error generating ATS score: {str(e)}")
                print(f"ERROR: Failed to generate ATS score: {str(e)}")
                flash(f"Error generating ATS score: {str(e)}")
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Deleted file: {file_path}")
                return redirect(url_for('index'))
        
        except Exception as e:
            logger.error(f"Error saving file: {str(e)}")
            print(f"ERROR: Failed to save file: {str(e)}")
            flash(f"Error uploading file: {str(e)}")
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Deleted file: {file_path}")
            return redirect(url_for('index'))
    
    flash('Invalid file type. Please upload a PDF.')
    logger.warning(f"Invalid file type uploaded: {file.filename}")
    print(f"WARNING: Invalid file type uploaded: {file.filename}")
    return redirect(url_for('index'))

if __name__ == '__main__':
    print("Starting Flask app in debug mode")
    app.run(debug=True)