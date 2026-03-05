from rest_framework.views import exception_handler

def custom_exception_handler(exc, context):
    """
    Custom exception handler for Django REST Framework that adds a standard
    'message' array field to all validation errors to simplify frontend parsing.
    """
    response = exception_handler(exc, context)

    # Standardize validation error responses
    if response is not None and isinstance(response.data, dict):
        messages = []
        for key, value in response.data.items():
            if isinstance(value, list):
                for err in value:
                    if isinstance(err, str): 
                        # Optionally prefix with key to be clear, e.g., "email: This field is required"
                        messages.append(err)
            elif isinstance(value, str) and key != 'message':
                messages.append(value)
        
        if messages:
            response.data['message'] = messages
            
    return response
