import sys
import os
import pprint
from pymongo import MongoClient

# Add parent dir to path so we can import if needed, though direct pymongo is easier
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
    client = MongoClient(uri)
    db = client["maxicourses"]
    collection = db["products"]
    
    ean = "7613035833289"
    product = collection.find_one({"ean": ean})
    
    if product:
        print(f"--- Product Found: {ean} ---")
        pprint.pprint(product)
    else:
        print(f"Product {ean} NOT FOUND in DB.")

if __name__ == "__main__":
    main()
