import pymupdf
import os

def parse_pdf(pdf_path, output_dir="images"):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        doc = pymupdf.open(pdf_path)
        print(f"✅ Opened PDF: {pdf_path}, Total pages: {doc.page_count}")
    except Exception as e:
        print(f"❌ Failure: {e}")
        return

    for page_num in range(doc.page_count):
        page = doc[page_num]
        text = page.get_text()
        print(f"\n=== Preview of Page {page_num + 1} text ===")
        print(text[:100].replace("\n", " "))
        
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            image_filename = f"{output_dir}/page{page_num + 1}_img{img_index + 1}.{image_ext}"
            with open(image_filename, "wb") as f:
                f.write(image_bytes)
            print(f"🖼️ Extracting the image: {image_filename}")
            
    doc.close()
    print(f"\n✅ PDF parsing completed!")

if __name__ == "__main__":
    target_pdf = "./test.pdf"
    parse_pdf(target_pdf)