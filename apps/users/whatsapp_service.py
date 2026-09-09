import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

def clean_phone_number(phone_number: str) -> str:
    if not phone_number:
        return ""
    digits = "".join(filter(str.isdigit, str(phone_number)))
    if len(digits) == 10:
        return f"91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        return f"91{digits[1:]}"
    return digits

def send_whatsapp_otp(phone_number: str, otp: str, lang_code: str = "en") -> dict:
    clean_phone = clean_phone_number(phone_number)
    if not clean_phone:
        return {"success": False, "error": "Invalid phone number"}

    phone_number_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "")
    access_token = getattr(settings, "WHATSAPP_ACCESS_TOKEN", "")
    api_url = getattr(settings, "WHATSAPP_API_URL", "https://graph.facebook.com/v20.0")
    template_name = getattr(settings, "WHATSAPP_OTP_TEMPLATE", "whatsapp_farmo_otp")

    if not phone_number_id or not access_token:
        error_msg = "WhatsApp credentials (WHATSAPP_PHONE_NUMBER_ID or WHATSAPP_ACCESS_TOKEN) are missing in settings."
        logger.error(error_msg)
        return {"success": False, "error": error_msg}

    endpoint = f"{api_url.rstrip('/')}/{phone_number_id}/messages"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang_code},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": str(otp)
                        }
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [
                        {
                            "type": "text",
                            "text": str(otp)
                        }
                    ]
                }
            ]
        }
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=12)
        res_data = response.json()

        if response.status_code in [200, 201]:
            logger.info(f"WhatsApp OTP sent successfully to {clean_phone}")
            return {"success": True, "data": res_data}

        if response.status_code == 400 and lang_code == "en":
            error_data = res_data.get("error", {})
            if "language" in str(error_data).lower():
                logger.warning("Retrying WhatsApp template with language code 'en_US'...")
                return send_whatsapp_otp(phone_number, otp, lang_code="en_US")

        logger.error(f"WhatsApp API returned error {response.status_code}: {res_data}")
        return {"success": False, "status_code": response.status_code, "error": res_data}

    except requests.RequestException as e:
        logger.exception(f"Network error connecting to WhatsApp API: {e}")
        return {"success": False, "error": str(e)}
