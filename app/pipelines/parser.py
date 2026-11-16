import pymupdf
import os

def extract_pdf_content(pdf_path: str, output_dir: str = "images") -> dict:
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        raise ValueError(f"❌Failure: {e}")

    all_text = ""
    extracted_images = []

    for page_num in range(doc.page_count):
        page = doc[page_num]
        all_text += page.get_text()
        
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            
            image_filename = f"{output_dir}/page{page_num + 1}_img{img_index + 1}.{image_ext}"
            with open(image_filename, "wb") as f:
                f.write(image_bytes)
            
            extracted_images.append(image_filename) 

    doc.close()
    
    return {
        "text": all_text,
        "images": extracted_images
    }