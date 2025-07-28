#These functions are made for next round for web integration
from flask import Flask, request, jsonify
from collections import defaultdict
import os
import re
import pdfplumber

UPLOAD_Folder='input'
os.makedirs(UPLOAD_Folder,exist_ok=True)


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

def Remove():
    filename=request.json.get('filename')
    filepath=os.path.join(UPLOAD_Folder,filename)
    print(filepath)
    
    try:
        os.remove(filepath)
        return jsonify({'message': f'{filename} has been removed successfully'}),200
    
    except Exception as e:
        return jsonify({'error': str(e)}),500
    

FONT_SIZE_MULTIPLIER = 1.2
HEADING_MIN_WORDS = 1
HEADING_MAX_WORDS = 20

def _sanitize_text(text: str) -> str:
    words = text.split()
    if not words:
        return ""
    unique_words = [words[0]]
    for i in range(1, len(words)):
        if words[i] != words[i-1]:
            unique_words.append(words[i])
    return " ".join(unique_words)

def _extract_outline_from_toc(pdf):
    toc_pattern = re.compile(r'^((\d+(\.\d+)*)\s+.*?)\s+\d+$')
    
    for page in pdf.pages:
        text = page.extract_text(x_tolerance=2, y_tolerance=2)
        if text and "Table of Contents" in text:
            outline = []
            lines = text.split('\n')
            for line in lines:
                match = re.search(r'^((\d+[\.\d]*)\.?\s+(.*?))\s+[. ]*\s+(\d+)$', line)
                if match:
                    section_number = match.group(2)
                    full_text = match.group(1).strip()
                    page_num = int(match.group(4))
                    
                    level = f"H{section_number.count('.') + 1}"
                    
                    outline.append({
                        "level": level,
                        "text": full_text,
                        "page": page_num
                    })
            if outline:
                return outline 
    return None

def _extract_visual_outline(pdf):
    """
    Extracts an outline based on font sizes and text positions.
    This is the fallback method if a ToC is not found.
    """
    all_text_objects = []
    font_stats = defaultdict(int)

    for page_num, page in enumerate(pdf.pages, 1):
        words = page.extract_words(extra_attrs=['fontname', 'size'])
        if not words:
            continue
        lines = defaultdict(list)
        for word in words:
            y_pos = round(word['top'], 1)
            size = round(word['size'], 1)
            line_key = (page_num, y_pos, size)
            lines[line_key].append({'text': word['text'], 'x0': word['x0']})
            font_stats[size] += 1
        
        for (p, y, s), word_list in lines.items():
            word_list.sort(key=lambda w: w['x0'])
            line_text = _sanitize_text(' '.join(w['text'] for w in word_list).strip())
            if line_text:
                all_text_objects.append({"text": line_text, "size": s, "page": p, "y_pos": y})

    if not all_text_objects:
        return None

    all_text_objects.sort(key=lambda x: (x['page'], x['y_pos']))
    

    body_font_size = max(font_stats, key=font_stats.get) if font_stats else 12.0
    heading_threshold = body_font_size * FONT_SIZE_MULTIPLIER
    heading_fonts = sorted([size for size in font_stats if size >= heading_threshold], reverse=True)
    font_to_level = {size: f"H{i+1}" for i, size in enumerate(heading_fonts[:3])}

    if not font_to_level:
        return None
    
    structured_outline = []
    for obj in all_text_objects:
        level = font_to_level.get(obj['size'])
        if level:
            text = obj['text']
            word_count = len(text.split())
            if (HEADING_MIN_WORDS <= word_count <= HEADING_MAX_WORDS and not text.strip().endswith('.') and any(c.isalpha() for c in text)):
                structured_outline.append({**obj, "level": level})

    if not structured_outline:
        return None
    
    merged_outline = []
    i = 0
    while i < len(structured_outline):
        current_heading = structured_outline[i]
        j = i + 1
        while j < len(structured_outline) and \
              structured_outline[j]['level'] == current_heading['level'] and \
              structured_outline[j]['page'] == current_heading['page'] and \
              (0 < (structured_outline[j]['y_pos'] - structured_outline[j-1]['y_pos']) < (current_heading['size'] * 1.5)):
            current_heading['text'] += " " + structured_outline[j]['text']
            j += 1
        
        final_heading = {"level": current_heading['level'], "text": current_heading['text'], "page": current_heading['page']}
        merged_outline.append(final_heading)
        i = j
    
    return merged_outline

def _find_document_title(pdf):
    first_page = pdf.pages[0]
    words = first_page.extract_words(extra_attrs=["fontname", "size"])
    if not words: return "Untitled"

    size_to_words = defaultdict(list)
    for word in words:
        size_to_words[round(word['size'], 1)].append(word)
    if not size_to_words: return "Untitled"
    largest_size = max(size_to_words.keys())
   
    title_words = []
    for size, word_list in size_to_words.items():
        if largest_size - size < 2: # Tolerance for slight size variations
            title_words.extend(word_list)

    title_words.sort(key=lambda w: (w['top'], w['x0']))
    return _sanitize_text(" ".join(w['text'] for w in title_words))

def get_pdf_outline(file_name):
    # file_name = request.json.get('filename')
    if not file_name:
        return {"error": "Filename is required"}

    file_path = os.path.join(UPLOAD_Folder, file_name)
    if not os.path.exists(file_path):
        return {"error": f"File '{file_name}' not found"}
    try:
        with pdfplumber.open(file_path) as pdf:
            document_title = _find_document_title(pdf)
            final_outline = _extract_outline_from_toc(pdf)
            
            if final_outline is None:
                final_outline = _extract_visual_outline(pdf)

            if final_outline is None:
                return {"title": document_title, "outline": [], "error": "Could not determine outline for this document."}

        return {"title": document_title, "outline": final_outline}

    except Exception as e:
        return {"error": f"An unexpected error occurred: {str(e)}"}
# if __name__ == '__main__':
#     app.run(debug=True,host="0.0.0.0")
