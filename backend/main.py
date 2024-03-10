from fastapi import FastAPI, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import shutil
import os
from fastapi.middleware.cors import CORSMiddleware
from fastapi import APIRouter, HTTPException
from openai import OpenAI
import base64
import requests
from pydantic import BaseModel

app = FastAPI()
client = OpenAI()
app.mount("/static", StaticFiles(directory="static"), name="static")

DATABASE_URL = "sqlite:///./test.db"
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Image(Base):
    __tablename__ = "images"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    describle = Column(String, default="", nullable=True)

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String)
    image_id = Column(Integer, ForeignKey('images.id'))
    image = relationship("Image", back_populates="comments")
    classify = Column(String, default="", nullable=True)

Image.comments = relationship("Comment", order_by=Comment.id, back_populates="image")

# Set up CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Allows only requests from your frontend
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

Base.metadata.create_all(bind=engine)

@app.post("/upload/")
async def create_upload_file(file: UploadFile = File(...)):
    with SessionLocal() as session:
        db_image = Image(filename=file.filename)
        session.add(db_image)
        session.commit()
        session.refresh(db_image)
        file_location = f"static/{file.filename}"
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
    return {"filename": file.filename, "id": db_image.id}

@app.get("/images/")
async def read_images():
    with SessionLocal() as session:
        images = session.query(Image).all()
        return images
    
@app.get("/images/{image_id}")
async def read_image(image_id: int):
    with SessionLocal() as session:
        image = session.get(Image, image_id)
        return image

class CommentModel(BaseModel):
    content: str
    image_id: int

class CommentResponseModel(BaseModel):
    id: int
    content: str
    image_id: int
    classify: str

    class Config:
        orm_mode = True

def gen_classify(content):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {
            "role": "system",
            "content": "I will give a feedback/comment about image. Your task evaluate the feedback and classify this feedback into: positive, negative, or neutral. Just response value as tag not sentence"
            },
            {
            "role": "user",
            "content": content
            },
            {
            "role": "assistant",
            "content": "positive"
            }
        ],
        temperature=1,
        max_tokens=256,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0
    )
    return response.choices[0].message.content

@app.post("/comments/", response_model=CommentResponseModel)
async def create_comment(comment: CommentModel):
    classify = gen_classify(comment.content)
    with SessionLocal() as session:
        db_comment = Comment(content=comment.content, image_id=comment.image_id, classify=classify)
        session.add(db_comment)
        session.commit()
        session.refresh(db_comment)  # Refresh the instance from the database
        return db_comment
    

@app.get("/comments/{image_id}")
async def read_comments(image_id: int):
    with SessionLocal() as session:
        comments = session.query(Comment).filter(Comment.image_id == image_id).all()
        return comments

def encode_image(image_path):
  with open(image_path, "rb") as image_file:
    return base64.b64encode(image_file.read()).decode('utf-8')



@app.get("/describle/{image_id}")
async def describle(image_id: int):
    if not image_id:
        raise HTTPException(status_code=400, detail="image_id cannot be empty")
    
    with SessionLocal() as session:
        image = session.get(Image, image_id)
    image_path = f"static/{image.filename}"

    # Getting the base64 string
    base64_image = encode_image(image_path)
    promting =  "Describe the image in max 50 words"
    response = client.chat.completions.create(
        model="gpt-4-vision-preview",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": promting},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        },
                    },
                ],
            }
        ],
        max_tokens=300,
    )
    
    describle_image = response.choices[0].message.content
    with SessionLocal() as session:
        image = session.get(Image, image_id)
        image.describle = describle_image
        session.commit()
    return {"describle": describle_image}
