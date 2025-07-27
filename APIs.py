from flask import Flask, request, jsonify
from collections import defaultdict
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

# --- Configuration Constants ---
# Determines how much larger a font must be than body text to be considered a heading.
FONT_SIZE_MULTIPLIER = 1.2
# Defines the valid word count range for a line to be a heading.
HEADING_MIN_WORDS = 1
HEADING_MAX_WORDS = 20


def _sanitize_text(text: str) -> str:
    """
    Cleans text by removing duplicated consecutive words that can appear in PDF extraction.
    e.g., "The The IPO IPO" becomes "The IPO". This is safer than character-level cleaning.
    """
    words = text.split()
    if not words:
        return ""
    
    # Use a list to store the unique words in order
    unique_words = [words[0]]
    for i in range(1, len(words)):
        if words[i] != words[i-1]:
            unique_words.append(words[i])
            
    return " ".join(unique_words)

def _extract_content_from_pdf(file_path: str) -> tuple[list, dict]:
    """
    Opens a PDF and extracts all text lines along with their properties.

    Returns:
        A tuple containing:
        - A list of all text block dictionaries.
        - A dictionary of font size frequencies.
    """
    text_blocks = []
    font_size_counts = defaultdict(int)

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            words = page.extract_words(extra_attrs=["fontname", "size"])
            if not words:
                continue
            
            # Group words into lines using their vertical position and font size as a key.
            lines_on_page = defaultdict(list)
            for word in words:
                key = (round(word["top"], 1), round(word["size"], 1))
                lines_on_page[key].append(word)
                font_size_counts[round(word["size"], 1)] += 1

            # Reconstruct each line from its words.
            for (y_pos, size), line_words in lines_on_page.items():
                line_words.sort(key=lambda w: w["x0"])
                raw_text = " ".join(w["text"] for w in line_words)
                cleaned_text = _sanitize_text(raw_text).strip()
                if cleaned_text:
                    text_blocks.append({
                        "text": cleaned_text, "size": size, "page": page_num, "y_pos": y_pos
                    })
    
    # Sort blocks by page and position for sequential processing.
    text_blocks.sort(key=lambda b: (b["page"], b["y_pos"]))
    return text_blocks, dict(font_size_counts)

def _identify_heading_levels(font_counts: dict) -> dict:
    """
    Analyzes font frequencies to determine which sizes correspond to headings.

    Returns:
        A dictionary mapping font sizes to heading levels (e.g., {18.0: "H1"}).
    """
    if not font_counts:
        return {}

    # The most frequent font size is assumed to be the body text.
    body_text_size = max(font_counts, key=font_counts.get)
    
    # Identify heading sizes as those significantly larger than the body text.
    heading_font_sizes = sorted(
        [size for size in font_counts if size >= body_text_size * FONT_SIZE_MULTIPLIER],
        reverse=True
    )
    
    # Map the top 3 heading sizes to H1, H2, and H3.
    return {size: f"H{i+1}" for i, size in enumerate(heading_font_sizes[:3])}

def _merge_adjacent_headings(heading_list: list) -> list:
    """
    Merges multi-line headings into a single heading entry.
    """
    if not heading_list:
        return []

    final_headings = []
    i = 0
    while i < len(heading_list):
        current = heading_list[i]
        
        # Look ahead to merge consecutive lines of the same heading.
        j = i + 1
        while j < len(heading_list):
            next_heading = heading_list[j]
            if (current["level"] == next_heading["level"] and
                current["page"] == next_heading["page"]):
                
                # Check if the vertical gap is small enough to indicate a multi-line heading.
                vertical_gap = next_heading["y_pos"] - heading_list[j-1]["y_pos"]
                if 0 < vertical_gap < (current["size"] * 1.5):
                    current["text"] += " " + next_heading["text"]
                    j += 1
                else:
                    break # The gap is too large, it's a separate heading.
            else:
                break
        
        # Clean up temporary keys before adding to the final list.
        del current["size"]
        del current["y_pos"]
        final_headings.append(current)
        i = j # Skip past the already merged items.
        
    return final_headings

def _find_document_title(outline: list) -> str:
    """
    Selects the most appropriate title from the final outline.
    """
    if not outline:
        return "Untitled"

    # Default to the very first heading as a fallback.
    title = outline[0]["text"]
    
    # Search for the highest-ranking heading (H1, then H2) to use as the title.
    for level in ["H1", "H2"]:
        found_title = next((item["text"] for item in outline if item["level"] == level), None)
        if found_title:
            title = found_title
            return title # Return as soon as the best level is found.
    
    return title

# --- Main API Endpoint ---

@app.route('/ExtractData', methods=['POST'])
def get_pdf_outline():
    """
    Main API endpoint to process a PDF and return its structured outline.
    """
    file_name = request.json.get('filename')

    file_path = os.path.join(UPLOAD_Folder, file_name)
    if not os.path.exists(file_path):
        return jsonify({"error": f"File '{file_name}' not found"}), 404

    try:
        # 1. Extract text and font data from the PDF.
        all_blocks, font_counts = _extract_content_from_pdf(file_path)
        if not all_blocks:
            return jsonify({"title": "Untitled", "outline": [], "error": "No text could be extracted."})

        # 2. Deduplicate text blocks to handle redundant text.
        unique_blocks = []
        seen_text_keys = set()
        for block in all_blocks:
            key = re.sub(r'\\s+', '', block["text"]).lower()
            if key not in seen_text_keys:
                unique_blocks.append(block)
                seen_text_keys.add(key)
        
        # 3. Identify which font sizes correspond to heading levels.
        size_to_level_map = _identify_heading_levels(font_counts)
        if not size_to_level_map:
             return jsonify({"title": "Untitled", "outline": [], "error": "Could not determine heading structure."})

        # 4. Filter for text blocks that are likely headings.
        heading_candidates = []
        for block in unique_blocks:
            level = size_to_level_map.get(block["size"])
            if level:
                word_count = len(block["text"].split())
                # Apply filters to ensure the line looks like a heading.
                if (HEADING_MIN_WORDS <= word_count <= HEADING_MAX_WORDS and
                    not block["text"].strip().endswith(".") and
                    any(c.isalpha() for c in block["text"])):
                    heading_candidates.append({**block, "level": level})

        # 5. Merge multi-line headings and select the title.
        final_outline = _merge_adjacent_headings(heading_candidates)
        document_title = _find_document_title(final_outline)

        return jsonify({"title": document_title, "outline": final_outline}), 200

    except Exception as e:
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True,host="0.0.0.0")
