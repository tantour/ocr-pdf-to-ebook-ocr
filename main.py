import base64
import re
import os
from mistralai import Mistral
import gradio as gr
from datetime import datetime
import json
from dotenv import load_dotenv
load_dotenv()

try:
    import pypandoc
    PANDOC_AVAILABLE = True
except ImportError:
    PANDOC_AVAILABLE = False


def ocr_pdf_to_markdown(pdf_path: str, output_md_path: str, api_key=os.getenv("MISTRAL_API_KEY")):
    # ...existing code...
    client = Mistral(api_key=api_key)
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    b64_pdf = base64.b64encode(pdf_bytes).decode()

    resp = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{b64_pdf}"
        },
        include_image_base64=True,
        table_format="html"
    )

    os.makedirs("outputs", exist_ok=True)

    with open(output_md_path, "w", encoding="utf-8") as f:
        for page in resp.pages:
            content = page.markdown
            
            if hasattr(page, 'images') and page.images:
                for img in page.images:
                    if img.image_base64:
                        image_uri = img.image_base64
                        if not image_uri.startswith("data:"):
                            image_uri = f"data:image/jpeg;base64,{image_uri}"
                        
                        img_id = re.escape(img.id)
                        pattern = rf"\({img_id}(\.[a-z]{{3,4}})?\)"
                        content = re.sub(pattern, f"({image_uri})", content)
            
            # Remove standalone page numbers (e.g. "5", "Page 5", "- 5 -")
            content = re.sub(r'(?m)^\s*(?:Page\s*)?\d+(?:\s*of\s*\d+)?\s*$', '', content)
            
            f.write(content)
        return output_md_path


def extract_first_image_as_cover(md_content, output_dir="outputs"):
    """
    Extract the first image from markdown content to use as cover.
    Returns: (cover_image_path, modified_markdown_content)
    """
    # Regex to find the first image in markdown: ![alt](url)
    # We specifically look for base64 data URIs which the OCR tool produces
    pattern = r'!\[.*?\]\((data:image\/([a-zA-Z]+);base64,([^\)]+))\)'
    match = re.search(pattern, md_content)
    
    if match:
        full_match = match.group(0)
        img_fmt = match.group(2)
        base64_data = match.group(3)
        
        # Save extracted image
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cover_filename = f"cover_{timestamp}.{img_fmt}"
        cover_path = os.path.join(output_dir, cover_filename)
        
        try:
            with open(cover_path, "wb") as f:
                f.write(base64.b64decode(base64_data))
                
            # Remove the image from the content
            modified_content = md_content.replace(full_match, "", 1)
            return cover_path, modified_content
        except Exception as e:
            print(f"Failed to extract cover image: {e}")
            return None, md_content
            
    return None, md_content


def markdown_to_epub(md_path: str, output_epub_path: str, cover_image_path: str = None):
    """Convert Markdown to EPUB using pandoc"""
    if not PANDOC_AVAILABLE:
        raise RuntimeError("Pandoc not installed. Install with: pip install pypandoc pandoc")
    
    extra_args = []
    if cover_image_path and os.path.exists(cover_image_path):
        extra_args.append(f'--epub-cover-image={cover_image_path}')

    pypandoc.convert_file(md_path, 'epub', outputfile=output_epub_path, extra_args=extra_args)
    return output_epub_path


def markdown_to_mobi(md_path: str, output_mobi_path: str, cover_image_path: str = None):
    """Convert Markdown to MOBI using pandoc"""
    if not PANDOC_AVAILABLE:
        raise RuntimeError("Pandoc not installed. Install with: pip install pypandoc pandoc")
    
    extra_args = []
    if cover_image_path and os.path.exists(cover_image_path):
        extra_args.append(f'--epub-cover-image={cover_image_path}')

    pypandoc.convert_file(md_path, 'mobi', outputfile=output_mobi_path, extra_args=extra_args)
    return output_mobi_path


def get_output_files():
    """Get list of all output files"""
    if not os.path.exists("outputs"):
        return []
    
    files = []
    for file in sorted(os.listdir("outputs"), reverse=True):
        file_path = os.path.join("outputs", file)
        if os.path.isfile(file_path):
            size = os.path.getsize(file_path)
            mod_time = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S")
            files.append(f"{file} ({size} bytes) - {mod_time}")
    
    return files


def delete_output_file(selected_file):
    """Delete a selected output file"""
    if not selected_file:
        return "Please select a file to delete", gr.update(choices=get_output_files())
    
    try:
        file_name = selected_file.split(" (")[0]
        file_path = os.path.join("outputs", file_name)
        
        if os.path.exists(file_path):
            os.remove(file_path)
            return f"Deleted: {file_name}", gr.update(choices=get_output_files())
        else:
            return "File not found", gr.update(choices=get_output_files())
    except Exception as e:
        return f"Error deleting file: {str(e)}", gr.update(choices=get_output_files())


def view_output_file(selected_file):
    """View content of selected output file"""
    if not selected_file:
        return "Please select a file to view"
    
    try:
        file_name = selected_file.split(" (")[0]
        file_path = os.path.join("outputs", file_name)
        
        if not os.path.exists(file_path):
            return "File not found"
        
        if file_name.endswith('.md'):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return f"Cannot preview {file_name.split('.')[-1]} files in text format"
    except Exception as e:
        return f"Error reading file: {str(e)}"


def process_pdf_gradio(pdf_file, export_format, manual_cover, auto_cover):
    """Wrapper function for Gradio interface"""
    if pdf_file is None:
        return None, "Please upload a PDF file"
    
    try:
        # Get original filename without extension
        original_name = os.path.splitext(os.path.basename(pdf_file))[0]
        
        # Determine target extension
        if export_format == "Markdown":
            target_ext = ".md"
        elif export_format == "EPUB":
            target_ext = ".epub"
        else:
            target_ext = ".mobi"
            
        # Find unique file name
        counter = 0
        while True:
            suffix = f"_{counter}" if counter > 0 else ""
            final_filename = f"{original_name}{suffix}{target_ext}"
            output_path = os.path.join("outputs", final_filename)
            if not os.path.exists(output_path):
                break
            counter += 1
            
        # Define intermediate markdown path
        if export_format == "Markdown":
            md_output_path = output_path
        else:
            # Use timestamp for temporary intermediate file to avoid collisions
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            md_output_path = f"outputs/temp_{timestamp}.md"
        
        # First, convert PDF to Markdown
        ocr_pdf_to_markdown(pdf_file, md_output_path)
        
        # Determine cover image
        cover_image_path = None
        extracted_cover_temp = None
        
        if manual_cover is not None:
            cover_image_path = manual_cover
        elif auto_cover:
            # Read the markdown content
            with open(md_output_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            extracted_path, new_content = extract_first_image_as_cover(content)
            
            if extracted_path:
                cover_image_path = extracted_path
                extracted_cover_temp = extracted_path # Keep track to delete later if needed
                # Update the markdown file without the cover image
                with open(md_output_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
        
        # Then convert to requested format
        if export_format == "Markdown":
            # If we extracted a cover in markdown mode, we might want to keep the modified markdown 
            # or maybe the user expects the original. 
            # For now, let's assume if they ask for Markdown + Auto Cover, they get the markdown with the image removed 
            # (since there is no "cover" concept in a single markdown file effectively aside from metadata)
            # But usually cover is for ebook formats. 
            pass # Just return the path as is usually
            
            return output_path, f"Conversion completed: {final_filename}"
        elif export_format == "EPUB":
            markdown_to_epub(md_output_path, output_path, cover_image_path)
            if os.path.exists(md_output_path):
                os.remove(md_output_path)
            if extracted_cover_temp and os.path.exists(extracted_cover_temp):
                os.remove(extracted_cover_temp)
            return output_path, f"Conversion to EPUB completed: {final_filename}"
        elif export_format == "MOBI":
            markdown_to_mobi(md_output_path, output_path, cover_image_path)
            if os.path.exists(md_output_path):
                os.remove(md_output_path)
            if extracted_cover_temp and os.path.exists(extracted_cover_temp):
                os.remove(extracted_cover_temp)
            return output_path, f"Conversion to MOBI completed: {final_filename}"
        
    except Exception as e:
        return None, f"Error: {str(e)}"


def download_output_file(selected_file):
    """Get path for downloading selected output file"""
    if not selected_file:
        return None
    
    try:
        file_name = selected_file.split(" (")[0]
        file_path = os.path.join("outputs", file_name)
        
        if os.path.exists(file_path):
            return file_path
        return None
    except Exception:
        return None


# Create Gradio interface with tabs
with gr.Blocks(title="pdf to ebook formats") as demo:
    gr.Markdown("# Arabic OCR - PDF to ebook Formats")
    gr.Markdown("Convert PDF documents to Markdown, EPUB, or MOBI formats")
    with gr.Tabs():
        # Tab 1: Convert PDF
        with gr.Tab("Convert PDF"):
            with gr.Row():
                with gr.Column():
                    pdf_input = gr.File(label="Upload PDF", file_types=[".pdf"])
                    export_format = gr.Dropdown(
                        choices=["Markdown", "EPUB", "MOBI"],
                        value="EPUB",
                        label="Export Format"
                    )
                    
                    gr.Markdown("### Cover Image Options")
                    manual_cover = gr.Image(type="filepath", label="Manual Cover Image")
                    auto_cover = gr.Checkbox(label="Use First Image as Cover (Auto-extract & Delete from body)", value=False)

                    convert_btn = gr.Button("Convert", variant="primary")
                
                with gr.Column():
                    output_file = gr.File(label="Download")
                    status_msg = gr.Textbox(label="Status", interactive=False)
            
            convert_btn.click(
                fn=process_pdf_gradio,
                inputs=[pdf_input, export_format, manual_cover, auto_cover],
                outputs=[output_file, status_msg]
            )
        
        # Tab 2: Manage Outputs
        with gr.Tab("Manage Outputs"):
            gr.Markdown("### View, Download, and Delete Past Outputs")
            
            with gr.Row():
                with gr.Column(scale=2):
                    file_list = gr.Dropdown(
                        choices=get_output_files(),
                        label="Select Output File",
                        interactive=True
                    )
                    refresh_btn = gr.Button("Refresh List")
                
                with gr.Column(scale=1):
                    view_btn = gr.Button("View", variant="secondary")
                    download_btn = gr.Button("Download", variant="primary")
                    delete_btn = gr.Button("Delete", variant="stop")
            
            with gr.Row():
                file_download = gr.File(label="Download File")
                delete_status = gr.Textbox(label="Status", interactive=False)
            
            file_preview = gr.Textbox(
                label="File Preview",
                lines=15,
                interactive=False,
                max_lines=20
            )

            refresh_btn.click(
                fn=lambda: gr.update(choices=get_output_files()),
                outputs=[file_list]
            )
            
            view_btn.click(
                fn=view_output_file,
                inputs=[file_list],
                outputs=[file_preview]
            )
            
            download_btn.click(
                fn=download_output_file,
                inputs=[file_list],
                outputs=[file_download]
            )
            
            delete_btn.click(
                fn=delete_output_file,
                inputs=[file_list],
                outputs=[delete_status, file_list]
            )


if __name__ == "__main__":
    demo.launch(favicon_path="favicon.ico")

