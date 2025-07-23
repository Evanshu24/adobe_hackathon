from flask import Flask, request, jsonify
import os
import re
import pdfplumber

app = Flask(__name__)

UPLOAD_Folder='UPLOADS'
os.makedirs(UPLOAD_Folder,exist_ok=True)

#This API adds pdfs to UPLOADS folder
@app.route('/AddFile', methods=['POST'])
def Add():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 500

    file=request.files['file']  # This will give a object which have .filename, .save and .read feature
    
    if file.filename=='':
        return jsonify({'error': 'No file is added'}), 500
    
    filename=file.filename
    file_type=filename.split('.').pop()
    if file_type!='pdf' :
        return jsonify({'message':"You can only upload pdf files"}),500
    
    filepath=os.path.join(UPLOAD_Folder, file.filename)
    print(filepath)
    file.save(filepath)

    return jsonify({'message': f'{file.filename} uploaded successfully'}), 200

#This API will delete pdfs from UPLOADS folder
@app.route('/RemoveFile', methods=['POST'])
def Remove():
    filename=request.json.get('filename')
    filepath=os.path.join(UPLOAD_Folder,filename)
    print(filepath)
    
    try:
        os.remove(filepath)
        return jsonify({'message': f'{filename} has been removed successfully'}),200
    
    except Exception as e:
        return jsonify({'error': str(e)}),500
    
#This API is for getting title and other headings from the pdfs
HEADING_THRESHOLD_MULTIPLIER = 1.2
MIN_HEADING_WORDS = 1 # Lowered to allow short headings
MAX_HEADING_WORDS = 20

# --- NEW: Function to clean duplicated characters ---
def clean_text(text):
    """
    Removes character duplication used for faux-bolding in some PDFs.
    Example: "LLeeccttuurree" -> "Lecture"
    """
    return re.sub(r'(.)\1', r'\1', text)

@app.route('/ExtractData', methods=['POST'])
def extract_outline():
    """
    API endpoint to extract a structured outline from a PDF file.
    Expects a JSON payload with a "filename" key.
    """
    filename = request.json.get('filename')
    if filename=='':
        return jsonify({"error": "Filename is required"}), 400

    filepath = os.path.join(UPLOAD_Folder, filename)

    try:
        # --- 1. Extract Text Objects and Font Statistics ---
        all_text_objects = []
        font_stats = {}
        with pdfplumber.open(filepath) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(extra_attrs=['fontname', 'size'])
                if not words:
                    continue

                lines = {}
                for word in words:
                    print(word)
                    print('\n')
                    y_pos = round(word['top'], 1)
                    size = round(word['size'], 1)
                    line_key = (page_num, y_pos, size)

                    if line_key not in lines:
                        lines[line_key] = []
                    lines[line_key].append({'text': word['text'], 'x0': word['x0']})
                    font_stats[size] = font_stats.get(size, 0) + 1

                for (p, y, s), word_list in lines.items():
                    word_list.sort(key=lambda w: w['x0'])
                    # Apply text cleaning right after joining words
                    line_text = clean_text(' '.join([w['text'] for w in word_list]).strip())
                    if line_text:
                        all_text_objects.append({
                            "text": line_text,
                            "size": s,
                            "page": p,
                            "y_pos": y
                        })

        if not all_text_objects:
            return jsonify({"title": "Untitled", "outline": [], "error": "No text could be extracted."}), 200

        all_text_objects.sort(key=lambda x: (x['page'], x['y_pos']))

        # --- 2. Deduplicate Text Objects ---
        unique_objects = []
        seen_texts = set()
        for obj in all_text_objects:
            text_key = re.sub(r'\s+', '', obj['text']).lower()
            if text_key not in seen_texts:
                unique_objects.append(obj)
                seen_texts.add(text_key)

        # --- 3. Analyze Fonts to Identify Heading Levels ---
        if not font_stats:
            return jsonify({"title": "Untitled", "outline": [], "error": "No font statistics found."}), 200

        sorted_by_frequency = sorted(font_stats.items(), key=lambda x: -x[1])
        body_font_size = sorted_by_frequency[0][0] if sorted_by_frequency else 12.0

        heading_threshold = body_font_size * HEADING_THRESHOLD_MULTIPLIER
        heading_fonts = sorted([size for size in font_stats if size >= heading_threshold], reverse=True)
        font_to_level = {size: f"H{i+1}" for i, size in enumerate(heading_fonts[:3])}

        # --- 4. Build the Initial (Unmerged) Outline ---
        structured_outline = []
        for obj in unique_objects:
            level = font_to_level.get(obj['size'])
            if level:
                text = obj['text']
                word_count = len(text.split())
                if (MIN_HEADING_WORDS <= word_count <= MAX_HEADING_WORDS and
                    not text.strip().endswith('.') and
                    any(c.isalpha() for c in text)):
                    structured_outline.append({
                        "level": level,
                        "text": text,
                        "page": obj['page'],
                        "y_pos": obj['y_pos'], # Keep y_pos for merging logic
                        "size": obj['size'] # Keep size for merging logic
                    })

        # --- 5. NEW: Merge Multi-Line Headings ---
        if not structured_outline:
            return jsonify({"title": "Untitled", "outline": []}), 200

        merged_outline = []
        i = 0
        while i < len(structured_outline):
            current_heading = structured_outline[i]
            j = i + 1
            # Check if the next heading can be merged with the current one
            while (j < len(structured_outline) and
                   structured_outline[j]['level'] == current_heading['level'] and
                   structured_outline[j]['page'] == current_heading['page']):
                   # Check vertical proximity
                   # A reasonable gap is less than the font size itself
                   vertical_gap = structured_outline[j]['y_pos'] - structured_outline[j-1]['y_pos']
                   if 0 < vertical_gap < (current_heading['size'] * 1.5):
                        current_heading['text'] += " " + structured_outline[j]['text']
                        j += 1
                   else:
                       break # Gap is too large, stop merging
            
            # Remove temporary keys before adding to final list
            del current_heading['y_pos']
            del current_heading['size']
            merged_outline.append(current_heading)
            i = j # Move main index past the merged items

        # --- 6. Determine Title from Final Merged Outline ---
        title = "Untitled" # Start with a default value

        if merged_outline:
            # As a fallback, set the title to the very first heading found
            title = merged_outline[0]['text']
            
            # Now, search for the best possible title in order of importance
            for level_to_find in ['H1', 'H2']:
                # Look for the first heading that matches the current level in the loop
                found_heading = next((item['text'] for item in merged_outline if item['level'] == level_to_find), None)
                
                if found_heading:
                    title = found_heading
                    break # Stop searching as we've found the highest-ranking title
                
        return jsonify({
            "title": title,
            "outline": merged_outline
        }), 200

    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

    
if __name__ == '__main__':
    app.run(debug=True)
