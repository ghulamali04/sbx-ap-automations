import os
import httpx
from fastapi import HTTPException

class ZohoAuth:
    def __init__(self):
        self.client_id = os.getenv("ZOHO_CLIENT_ID")
        self.client_secret = os.getenv("ZOHO_CLIENT_SECRET")
        self.redirect_uri = os.getenv("ZOHO_REDIRECT_URI")
        # Strip any trailing slash so we don't build ".../com//oauth/...".
        self.accounts_url = (os.getenv("ZOHO_ACCOUNTS_URL") or "").rstrip("/")

    def get_authorization_url(
        self, scope: str = "ZohoProjects.portals.READ,ZohoProjects.projects.READ"
    ) -> str:
        return (
            f"{self.accounts_url}/oauth/v2/auth"
            f"?client_id={self.client_id}"
            f"&response_type=code"
            f"&redirect_uri={self.redirect_uri}"
            f"&access_type=offline"
            f"&prompt=consent"
            f"&scope={scope}"
        )

    async def exchange_code_for_tokens(self, code: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.accounts_url}/oauth/v2/token",
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if response.status_code != 200:
            error_detail = response.json() if response.text else "Unknown error"
            raise HTTPException(
                status_code=400, 
                detail=f"Zoho token exchange failed: {error_detail}"
            )
        return response.json()