"""Subscriber models — mirrored in frontend/src/lib/types.ts."""
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class Subscriber(BaseModel):
    id: str
    email: EmailStr
    status: Literal["pending", "confirmed", "unsubscribed"]
    created_at: str
    confirmed_at: Optional[str] = None
    last_sent_at: Optional[str] = None
    send_count: int = 0
    source: str = "website"


class SubscribeRequest(BaseModel):
    email: EmailStr
    source: str = "website"


class SubscribeResponse(BaseModel):
    status: Literal["pending", "already_confirmed", "resent"]
    message: str
    mail_sent: bool
    mail_error: str = ""


class ConfirmResponse(BaseModel):
    status: Literal["confirmed", "already_confirmed", "invalid"]
    message: str
    email: str = ""
    issue_sent: bool = False


class SubscriberStats(BaseModel):
    confirmed: int
    pending: int
    unsubscribed: int
    total: int
    mail_configured: bool
    sender: str
    recent: List[Subscriber] = Field(default_factory=list)


class SendIssueRequest(BaseModel):
    test_email: Optional[EmailStr] = None
    attach_pdf: bool = True


class SendIssueResponse(BaseModel):
    sent: int
    failed: int
    skipped: int
    test_mode: bool
    issue_title: str
    errors: List[str] = Field(default_factory=list)
