from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from flask_cors import CORS
import ast
import hashlib
import re
from itertools import combinations
import os
import fitz  # PyMuPDF
from docx import Document

# Create Flask app instance
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max file size

# Enable CORS after the app is created
CORS(app, resources={r"/*": {"origins": "https://plagiarismhecker.vercel.app"}})
SUPPORTED_LANGUAGES = {
    'py': 'Python',
    'java': 'Java',
    'cpp': 'C++',
    'js': 'JavaScript',
    'php': 'PHP',
    'rb': 'Ruby',
    'go': 'Go',
    'swift': 'Swift',
    'kt': 'Kotlin',
    'ts': 'TypeScript',
    'txt': 'Text',
    'pdf': 'PDF',
    'docx': 'DOCX'
}

# Function to generate AST hash for code
def get_ast_hash(code):
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                node.name = 'REDACTED'
            elif isinstance(node, ast.arg):
                node.arg = 'REDACTED'
            elif isinstance(node, ast.Name):
                node.id = 'REDACTED'
        return hashlib.md5(ast.dump(tree).encode()).hexdigest()
    except Exception as e:
        print(f"Error parsing code: {e}")
        return None

# Function to generate text hash
def get_text_hash(text):
    return hashlib.md5(re.sub(r'\b\w+\b', 'TOKEN', text).encode()).hexdigest()

# Function to generate token hash
def get_tokens(code):
    code = re.sub(r'\b\w+\b', 'TOKEN', code)
    return hashlib.md5(code.encode()).hexdigest()

# Extract text from PDF
def extract_text_from_pdf(file_path):
    text = ""
    try:
        pdf_document = fitz.open(file_path)
        for page_num in range(pdf_document.page_count):
            page = pdf_document.load_page(page_num)
            text += page.get_text()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
    return text

# Extract text from DOCX
def extract_text_from_docx(file_path):
    text = ""
    try:
        doc = Document(file_path)
        for paragraph in doc.paragraphs:
            text += paragraph.text + '\n'
    except Exception as e:
        print(f"Error extracting text from DOCX: {e}")
    return text

# Get text from file based on extension
def get_text_from_file(file_path):
    _, ext = os.path.splitext(file_path)
    ext = ext.lstrip('.').lower()

    if ext == 'pdf':
        return extract_text_from_pdf(file_path)
    elif ext == 'docx':
        return extract_text_from_docx(file_path)
    else:
        with open(file_path, 'r') as file:
            return file.read()

# Compare two files for similarity
def compare_files(file1, file2, is_code=True):
    content1 = get_text_from_file(file1)
    content2 = get_text_from_file(file2)

    hash_table = {}
    lines1 = content1.splitlines()
    lines2 = content2.splitlines()
    overlap_count = 0
    overlapping_lines = []

    for line in lines1:
        if is_code:
            normalized_hash = get_ast_hash(line)
            tokenized_hash = get_tokens(line)
        else:
            normalized_hash = get_text_hash(line)
            tokenized_hash = None
        
        if normalized_hash:
            hash_table[normalized_hash] = line
        if tokenized_hash:
            hash_table[tokenized_hash] = line

    for line in lines2:
        if is_code:
            normalized_hash = get_ast_hash(line)
            tokenized_hash = get_tokens(line)
        else:
            normalized_hash = get_text_hash(line)
            tokenized_hash = None

        if normalized_hash in hash_table or (tokenized_hash and tokenized_hash in hash_table):
            overlapping_lines.append(line)
            overlap_count += 1

    total_lines = len(lines2)
    overlap_percentage = (overlap_count / total_lines) * 100 if total_lines > 0 else 0

    return {
        "overlap_percentage": overlap_percentage,
        "overlap_count": overlap_count,
        "overlapping_lines": overlapping_lines
    }

# Read code files from file paths
def read_code_files(file_paths):
    code_contents = {}
    for file_path in file_paths:
        code_contents[file_path] = get_text_from_file(file_path)
    return code_contents

# Compare two codes for similarity
def compare_two_codes(code1, code2, is_code=True):
    lines1 = code1.splitlines()
    lines2 = code2.splitlines()
    hash_table = set()
    overlap_count = 0

    for line in lines1:
        if is_code:
            normalized_hash = get_ast_hash(line)
            tokenized_hash = get_tokens(line)
        else:
            normalized_hash = get_text_hash(line)
            tokenized_hash = None
        
        if normalized_hash:
            hash_table.add(normalized_hash)
        if tokenized_hash:
            hash_table.add(tokenized_hash)

    for line in lines2:
        if is_code:
            normalized_hash = get_ast_hash(line)
            tokenized_hash = get_tokens(line)
        else:
            normalized_hash = get_text_hash(line)
            tokenized_hash = None

        if normalized_hash in hash_table or (tokenized_hash and tokenized_hash in hash_table):
            overlap_count += 1

    total_lines = len(lines2)
    overlap_percentage = (overlap_count / total_lines) * 100 if total_lines > 0 else 0
    return overlap_percentage, overlap_count

# Group similar files
def group_similar_files(file_paths):
    file_contents = read_code_files(file_paths)
    similarities = []

    for file1, file2 in combinations(file_paths, 2):
        is_code = os.path.splitext(file1)[1].lstrip('.') not in ['txt', 'pdf', 'docx']
        similarity_percentage, _ = compare_two_codes(file_contents[file1], file_contents[file2], is_code)
        similarities.append((file1, file2, similarity_percentage))

    return sorted(similarities, key=lambda x: x[2], reverse=True)

# Validate file path
def validate_file_path(file_path):
    if not os.path.exists(file_path):
        raise ValueError(f"File not found: {file_path}")

# Validate file extension
def validate_file_extension(file_path):
    _, ext = os.path.splitext(file_path)
    ext = ext.lstrip('.').lower()
    if ext not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported file extension: {ext}")

# Validate request data
def validate_request_data(data, required_fields):
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
        if field == 'file_paths':
            if not isinstance(data[field], list):
                raise ValueError(f"Field {field} must be a list of strings")
            for path in data[field]:
                if not isinstance(path, str):
                    raise ValueError(f"Each path in {field} must be a string")
        else:
            if not isinstance(data[field], str):
                raise ValueError(f"Field {field} must be a string")

# Validate that all files have the same language
def validate_all_same_language(file_paths):
    extensions = {os.path.splitext(path)[1].lstrip('.').lower() for path in file_paths}
    if len(extensions) > 1:
        raise ValueError("Files must all be of the same supported language")

# Handle HTTP errors
@app.errorhandler(HTTPException)
def handle_exception(e):
    """Handle HTTP errors."""
    response = e.get_response()
    response.data = jsonify({
        "code": e.code,
        "name": e.name,
        "description": e.description
    }).data
    response.content_type = "application/json"
    return response

# Handle non-HTTP errors
@app.errorhandler(Exception)
def handle_generic_exception(e):
    """Handle non-HTTP errors."""
    response = jsonify({
        "code": 500,
        "name": "Internal Server Error",
        "description": str(e)
    })
    response.content_type = "application/json"
    return response

# Route to compare two files
# Route to compare two files
@app.route('/compare', methods=['POST'])
def compare():
    try:
        file1 = request.files['file1']
        file2 = request.files['file2']

        file1_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file1.filename))
        file2_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file2.filename))
        file1.save(file1_path)
        file2.save(file2_path)

        ext1 = os.path.splitext(file1_path)[1].lstrip('.').lower()
        ext2 = os.path.splitext(file2_path)[1].lstrip('.').lower()
        is_code = ext1 not in ['txt', 'pdf', 'docx'] and ext2 not in ['txt', 'pdf', 'docx']
        result = compare_files(file1_path, file2_path, is_code)

        # Delete files after comparison
        os.remove(file1_path)
        os.remove(file2_path)

        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return handle_generic_exception(e)

# Route to group similar files
# Route to group similar files
@app.route('/group', methods=['POST'])
def group():
    try:
        files = request.files.getlist('files')
        file_paths = []

        for file in files:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
            file.save(file_path)
            file_paths.append(file_path)

        for path in file_paths:
            validate_file_path(path)
            validate_file_extension(path)

        validate_all_same_language(file_paths)

        result = group_similar_files(file_paths)

        # Delete files after grouping
        for file_path in file_paths:
            os.remove(file_path)

        return jsonify({"grouped_files": result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return handle_generic_exception(e)


# Run the application
if __name__ == '__main__':
    app.run(debug=True)
