import json
import os
import uuid
from google.cloud import aiplatform, storage
from vertexai.language_models import TextEmbeddingModel

# Lấy các biến môi trường
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
INDEX_NAME = "coercion_scenarios_index"
ENDPOINT_NAME = "coercion_scenarios_endpoint"

def create_embeddings_and_upload():
    print("1. Khởi tạo Vertex AI...")
    aiplatform.init(project=PROJECT_ID, location=LOCATION)
    
    # Load mô hình embedding
    embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    
    # Đọc dữ liệu seed
    with open("../data/coercion_seed.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"2. Đang tạo embedding cho {len(data)} kịch bản...")
    jsonl_lines = []
    
    for item in data:
        # Lấy embedding
        embeddings = embedding_model.get_embeddings([item["text"]])
        vector = embeddings[0].values
        
        # Format JSONL cho Vector Search
        # Vertex AI Vector Search yêu cầu format: {"id": "string", "embedding": [float]}
        jsonl_line = {
            "id": item["category"], # Lưu ID là category (chiêu thức) để khi match trả về cờ rủi ro luôn
            "embedding": vector
        }
        jsonl_lines.append(json.dumps(jsonl_line))
        
    # Ghi ra file JSONL tạm
    local_file = "coercion_embeddings.jsonl"
    with open(local_file, "w", encoding="utf-8") as f:
        f.write("\n".join(jsonl_lines))
        
    print("3. Upload lên Google Cloud Storage...")
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)
    
    # Tạo thư mục tạm trên GCS (Vertex AI Index yêu cầu dữ liệu nằm trong folder GCS)
    gcs_prefix = "vector_search/coercion_data"
    blob = bucket.blob(f"{gcs_prefix}/{local_file}")
    blob.upload_from_filename(local_file)
    gcs_uri = f"gs://{BUCKET_NAME}/{gcs_prefix}/"
    print(f"Đã upload dữ liệu vector lên {gcs_uri}")
    
    return gcs_uri

def deploy_vector_index(gcs_uri: str):
    print("4. Bắt đầu tạo Vertex AI Vector Search Index (Quá trình này có thể mất ~30-60 phút)...")
    
    # Xóa index cũ nếu cần hoặc tạo mới với timestamp
    unique_suffix = str(uuid.uuid4())[:8]
    index_name_uniq = f"{INDEX_NAME}_{unique_suffix}"
    
    my_index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
        display_name=index_name_uniq,
        contents_delta_uri=gcs_uri,
        dimensions=768,
        approximate_neighbors_count=5,
        distance_measure_type="COSINE_DISTANCE"
    )
    print(f"Index tạo thành công: {my_index.resource_name}")
    
    print("5. Bắt đầu tạo Endpoint...")
    my_index_endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
        display_name=ENDPOINT_NAME,
        public_endpoint_enabled=True # Dùng public endpoint để test cho dễ, có thể chuyển qua private
    )
    print(f"Endpoint tạo thành công: {my_index_endpoint.resource_name}")
    
    print("6. Deploy Index lên Endpoint (Quá trình này có thể mất ~20-30 phút)...")
    my_index_endpoint.deploy_index(
        index=my_index,
        deployed_index_id=f"deployed_{index_name_uniq}"
    )
    print("=== DEPLOY THÀNH CÔNG ===")
    print(f"INDEX_ENDPOINT_ID: {my_index_endpoint.resource_name}")
    print(f"DEPLOYED_INDEX_ID: deployed_{index_name_uniq}")
    
    # Ghi ra file text kết quả
    with open("deploy_result.txt", "w") as f:
        f.write(f"INDEX_ENDPOINT_ID={my_index_endpoint.resource_name}\n")
        f.write(f"DEPLOYED_INDEX_ID=deployed_{index_name_uniq}\n")
        
if __name__ == "__main__":
    if not PROJECT_ID or not BUCKET_NAME:
        print("Vui lòng set biến môi trường GOOGLE_CLOUD_PROJECT và GCS_BUCKET_NAME trước khi chạy.")
        exit(1)
        
    gcs_uri = create_embeddings_and_upload()
    deploy_vector_index(gcs_uri)
