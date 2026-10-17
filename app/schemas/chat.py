from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=2000, description="The visitor's question")
    session_token: str | None = Field(None, max_length=64,
                                      description="Token from the previous reply. Leave out to start a new chat.")

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Please type a question.")
        return v

    @field_validator("session_token")
    @classmethod
    def blank_token_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class FeedbackRequest(BaseModel):
    message_id: int = Field(..., ge=1, description="The message_id returned with the answer")
    value: str = Field(..., pattern="^(up|down|clear)$", description="up = helpful, down = not helpful, clear = remove vote")
    comment: str | None = Field(None, max_length=500, description="Optional: what was wrong")

    @field_validator("comment")
    @classmethod
    def blank_comment_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None
