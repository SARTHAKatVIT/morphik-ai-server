from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
from morphik import Morphik
import requests
from io import BytesIO
import cloudinary
import cloudinary.uploader
import uuid
import re

load_dotenv()
URI = os.environ.get("URI")

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

app = Flask(__name__)


@app.route("/")
def home():
    return jsonify({"message": "API server is running"})


@app.route("/api/v1/ingest", methods=["GET", "POST"])
def handle_ingestion():
    if request.method == "POST":
        data = request.get_json()
        file_url = data.get("file_url")
        uid = data.get("user_id")
        if not file_url:
            return jsonify({"error": "Missing file_url"}), 400
        if not uid:
            return jsonify({"error": "Missing user_id"}), 400

        try:
            morphik = Morphik(uri=URI)

            user_scope = morphik.signin(uid)

            pdf_file = BytesIO(requests.get(file_url).content)
            doc = user_scope.ingest_file(
                file=pdf_file,
                use_colpali=True,
                filename="demo",  # TODO : change the filename
            )
            doc.wait_for_completion()

            return jsonify({"status": "success"}), 201
        except Exception as e:
            return jsonify({"status": "Failed to ingest", "details": str(e)}), 500

    return jsonify({"status": "success", "message": "API route active"})


@app.route("/api/v1/retrieval", methods=["GET", "POST"])
def handle_retrieval():
    if request.method == "POST":
        data = request.get_json()
        query = data.get("query")
        uid = data.get("user_id")

        if not query:
            return jsonify({"error": "Missing query"}), 400
        if not uid:
            return jsonify({"error": "Missing user_id"}), 400

        try:
            morphik = Morphik(uri=URI)
            user_scope = morphik.signin(uid)
            chunks = user_scope.retrieve_chunks(query=query, use_colpali=True, k=3)
            print(f"Found {len(chunks)} chunks related to query: {query}")
            base64_chunks = []
            text_chunks = []

            for chunk in chunks:
                raw_chunk = {}
                is_base64_content = False

                for attr in dir(chunk):
                    if not attr.startswith("_") and not callable(getattr(chunk, attr)):
                        try:
                            # For content, handle specifically
                            if attr == "content":
                                if hasattr(chunk.content, "as_base64"):
                                    try:
                                        content_base64 = chunk.content.as_base64()
                                        raw_chunk["content"] = content_base64
                                        is_base64_content = True
                                    except:
                                        content_str = str(chunk.content)
                                        raw_chunk["content"] = content_str
                                        # Check if the content string contains base64-encoded image data
                                        if (
                                            content_str.startswith("data:image")
                                            and ";base64," in content_str
                                        ):
                                            is_base64_content = True
                                else:
                                    content_str = str(chunk.content)
                                    raw_chunk["content"] = content_str
                                    # Check if the content string contains base64-encoded image data
                                    if (
                                        content_str.startswith("data:image")
                                        and ";base64," in content_str
                                    ):
                                        is_base64_content = True
                            else:
                                # For all other attributes
                                value = getattr(chunk, attr)
                                if isinstance(
                                    value, (str, int, float, bool, type(None))
                                ):
                                    raw_chunk[attr] = value
                                else:
                                    raw_chunk[attr] = str(value)
                        except Exception as attr_err:
                            print(
                                f"Error serializing attribute {attr}: {str(attr_err)}"
                            )

                # Handle base64 content - upload to Cloudinary
                if is_base64_content:
                    try:
                        # Get the base64 content
                        content = raw_chunk["content"]

                        # If the content is a data URL, extract the base64 part
                        if content.startswith("data:"):
                            # Extract the mime type and base64 data
                            mime_match = re.match(r"data:([^;]+);base64,(.+)", content)
                            if mime_match:
                                mime_type = mime_match.group(1)
                                base64_data = mime_match.group(
                                    2
                                )  # Generate a file extension for reference
                                file_extension = mime_type.split("/")[-1]

                                # Upload to Cloudinary
                                upload_result = cloudinary.uploader.upload(
                                    f"data:{mime_type};base64,{base64_data}",
                                    folder=f"morphik/{uid}",
                                    public_id=str(uuid.uuid4()),
                                    resource_type="auto",
                                )

                                # Replace base64 content with Cloudinary URL
                                raw_chunk["content"] = upload_result["secure_url"]
                                raw_chunk["image_url"] = upload_result["secure_url"]
                                raw_chunk["content_type"] = "image"

                        base64_chunks.append(raw_chunk)
                    except Exception as upload_err:
                        print(f"Error uploading to Cloudinary: {str(upload_err)}")
                        # Keep the original base64 content if upload fails
                        base64_chunks.append(raw_chunk)
                else:
                    raw_chunk["content_type"] = "text"
                    text_chunks.append(raw_chunk)

            print(
                f"Found {len(base64_chunks)} chunks with images uploaded to Cloudinary and {len(text_chunks)} text chunks"
            )

            return jsonify(
                {"image_content": base64_chunks, "text_content": text_chunks}
            )

        except Exception as e:
            return (
                jsonify({"error": "Failed to retrieve chunks", "details": str(e)}),
                500,
            )

    return jsonify({"status": "success", "message": "Retrieval API route active"})


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
