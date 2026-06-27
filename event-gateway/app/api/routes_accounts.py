from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from app.clients.account_service import AccountServiceClient, AccountServiceUnavailable, get_account_client
router=APIRouter(prefix="/accounts",tags=["accounts"])
@router.get("/{account_id}/balance")
async def get_balance(account_id:str,client:AccountServiceClient=Depends(get_account_client)):
    try: response=await client.get_balance(account_id)
    except AccountServiceUnavailable:
        raise HTTPException(503,detail={"code":"ACCOUNT_SERVICE_UNAVAILABLE","message":"Account information is temporarily unavailable","retryable":True})
    return JSONResponse(status_code=response.status_code,content=response.json())
