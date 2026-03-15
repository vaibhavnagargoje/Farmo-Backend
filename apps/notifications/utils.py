from firebase_admin import messaging

def send_push_notification(user, title, body, data=None):
    """
    Sends an FCM push notification to all devices registered by the user.
    """
    if data is None:
        data = {}

    # Ensure data dict only contains strings as required by FCM messages
    data = {str(k): str(v) for k, v in data.items()}

    # Get all active tokens for this user
    tokens = user.fcm_tokens.values_list('token', flat=True)
    
    if not tokens:
        return {'success': 0, 'failure': 0, 'responses': []}

    # Create the MulticastMessage
    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=data,
        tokens=list(tokens),
    )

    try:
        response = messaging.send_each_for_multicast(message)
        return {
            'success': response.success_count,
            'failure': response.failure_count,
            'responses': response.responses,
        }
    except Exception as e:
        print(f"Error sending FCM multicast: {e}")
        return {'success': 0, 'failure': len(tokens), 'error': str(e)}
