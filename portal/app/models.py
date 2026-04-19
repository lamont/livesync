from pydantic import BaseModel


class User(BaseModel):
    email: str
    groups: list[str] = []
    is_admin: bool = False


class VaultCreate(BaseModel):
    name: str
    encrypted_only: bool = False


class VaultInfo(BaseModel):
    name: str
    owner: str
    members: list[str] = []
    groups: list[str] = []
    encrypted_only: bool = False


class VaultUpdate(BaseModel):
    encrypted_only: bool | None = None


class MembersUpdate(BaseModel):
    add: list[str] = []
    remove: list[str] = []
