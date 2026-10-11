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


FCM_MULTICAST_LIMIT = 500


def send_push_to_tokens(tokens, title, body, data=None):
    """
    Sends one FCM push notification to many device tokens, in batches of 500
    (the FCM multicast limit). Returns total success and failure counts.
    """
    data = {str(k): str(v) for k, v in (data or {}).items()}
    tokens = list(tokens)
    success = failure = 0
    for start in range(0, len(tokens), FCM_MULTICAST_LIMIT):
        batch = tokens[start:start + FCM_MULTICAST_LIMIT]
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=data,
            tokens=batch,
        )
        try:
            response = messaging.send_each_for_multicast(message)
            success += response.success_count
            failure += response.failure_count
        except Exception as e:
            print(f"Error sending FCM multicast batch: {e}")
            failure += len(batch)
    return {'success': success, 'failure': failure}
