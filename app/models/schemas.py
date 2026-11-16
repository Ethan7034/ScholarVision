from pydantic import BaseModel

class UserCreate(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

# ... 把之前写的 AnalysisResponse 留在这里 ...
class AnalysisResponse(BaseModel):
    status: str
    filename: str
    extracted_text_length: int
    analyzed_image: str
    vlm_result: str

class WarningResponse(BaseModel):
    status: str
    message: str
    text_length: int