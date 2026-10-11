"""Forms for the App control pages: maintenance, app versions, announcements, broadcasts."""

from django import forms
from django.core.validators import MaxLengthValidator

from appcontrol.models import Announcement, AppControl, AppRelease, Audience, Broadcast

from .widgets import TEXT_ATTRS, TEXTAREA_ATTRS, _apply

OTHER_LANGUAGES = (('hi', 'Hindi'), ('mr', 'Marathi'))
BROADCAST_MESSAGE_LIMIT = 500
DATETIME_FORMAT = '%Y-%m-%dT%H:%M'
ALLOWED_LINK_PREFIXES = ('https://', 'http://', 'tel:', 'mailto:', 'whatsapp:', 'market://')


def datetime_widget():
    return forms.DateTimeInput(attrs={**TEXT_ATTRS, 'type': 'datetime-local'}, format=DATETIME_FORMAT)


class TranslatedFieldsMixin:
    """
    For each name in `translated_fields`, adds `<name>_hi` and `<name>_mr`
    inputs and stores them in the model's `<name>_translations` JSON field.
    English stays in the model field itself.
    """
    translated_fields = ()

    def add_translation_fields(self):
        for name in self.translated_fields:
            base = self.fields[name]
            saved = getattr(self.instance, f'{name}_translations', None) or {}
            for code, language in OTHER_LANGUAGES:
                is_long = isinstance(base.widget, forms.Textarea)
                widget = forms.Textarea(attrs=dict(TEXTAREA_ATTRS)) if is_long else forms.TextInput(attrs=dict(TEXT_ATTRS))
                self.fields[f'{name}_{code}'] = forms.CharField(
                    label=f'{base.label} ({language})',
                    required=False,
                    max_length=getattr(base, 'max_length', None),
                    widget=widget,
                    initial=saved.get(code, ''),
                )

    def translation_rows(self):
        """[(label, [('EN', field), ('HI', field), ('MR', field)])] for the template."""
        rows = []
        for name in self.translated_fields:
            fields = [('EN', self[name])] + [(code.upper(), self[f'{name}_{code}']) for code, _ in OTHER_LANGUAGES]
            rows.append((self.fields[name].label, fields))
        return rows

    def save(self, commit=True):
        instance = super().save(commit=False)
        for name in self.translated_fields:
            setattr(instance, f'{name}_translations', {
                code: self.cleaned_data[f'{name}_{code}'].strip()
                for code, _ in OTHER_LANGUAGES
                if (self.cleaned_data.get(f'{name}_{code}') or '').strip()
            })
        if commit:
            instance.save()
        return instance


class MaintenanceForm(TranslatedFieldsMixin, forms.ModelForm):
    translated_fields = ('maintenance_title', 'maintenance_message')

    class Meta:
        model = AppControl
        fields = [
            'maintenance_on', 'maintenance_title', 'maintenance_message',
            'maintenance_ends_at', 'block_api_during_maintenance',
        ]
        labels = {
            'maintenance_on': 'Maintenance mode',
            'maintenance_title': 'Title',
            'maintenance_message': 'Message',
            'maintenance_ends_at': 'Back by (optional)',
            'block_api_during_maintenance': 'Also refuse app requests',
        }
        widgets = {'maintenance_ends_at': datetime_widget()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['maintenance_ends_at'].input_formats = [DATETIME_FORMAT]
        _apply(self.fields)
        self.fields['maintenance_title'].widget.attrs['placeholder'] = 'We are improving Farmo'
        self.fields['maintenance_message'].widget.attrs['placeholder'] = 'Farmo will be back shortly. Thank you for your patience.'
        self.add_translation_fields()


class ReleaseForm(TranslatedFieldsMixin, forms.ModelForm):
    translated_fields = ('update_title', 'update_message')

    class Meta:
        model = AppRelease
        fields = [
            'latest_version', 'latest_build', 'min_supported_build', 'soft_update_enabled',
            'store_url', 'update_title', 'update_message',
        ]
        labels = {
            'latest_version': 'Latest version',
            'latest_build': 'Latest build number',
            'min_supported_build': 'Minimum build allowed',
            'soft_update_enabled': 'Offer the update to older builds',
            'store_url': 'Store link',
            'update_title': 'Update title',
            'update_message': "What's new",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields['latest_version'].widget.attrs['placeholder'] = 'e.g. 1.0.27'
        self.fields['latest_build'].widget.attrs['placeholder'] = 'e.g. 27'
        self.fields['update_title'].widget.attrs['placeholder'] = 'A new version of Farmo is available'
        self.add_translation_fields()

    def clean(self):
        cleaned = super().clean()
        latest, minimum = cleaned.get('latest_build') or 0, cleaned.get('min_supported_build') or 0
        if minimum and not latest:
            self.add_error('latest_build', 'Set the latest build before forcing updates.')
        elif minimum > latest:
            self.add_error(
                'min_supported_build',
                "The minimum can't be higher than the latest build, or even the newest app would be blocked.",
            )
        return cleaned


class AnnouncementForm(TranslatedFieldsMixin, forms.ModelForm):
    translated_fields = ('title', 'message', 'cta_label')

    class Meta:
        model = Announcement
        fields = [
            'title', 'message', 'cta_label', 'cta_url',
            'placement', 'style', 'audience', 'show_on', 'image',
            'starts_at', 'ends_at', 'priority', 'is_active', 'dismissible',
        ]
        labels = {
            'cta_label': 'Button text (optional)',
            'cta_url': 'Button link (optional)',
            'show_on': 'Show on',
            'starts_at': 'Show from',
            'ends_at': 'Show until (optional)',
            'is_active': 'Active',
            'dismissible': 'People can close it',
        }
        widgets = {'starts_at': datetime_widget(), 'ends_at': datetime_widget()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('starts_at', 'ends_at'):
            self.fields[name].input_formats = [DATETIME_FORMAT]
        _apply(self.fields)
        self.fields['cta_url'].widget.attrs['placeholder'] = 'https://... or tel:+91...'
        self.add_translation_fields()

    def clean_cta_url(self):
        url = (self.cleaned_data.get('cta_url') or '').strip()
        if url and not url.lower().startswith(ALLOWED_LINK_PREFIXES):
            raise forms.ValidationError('Use a link starting with https://, tel:, mailto: or whatsapp:.')
        return url

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('cta_url') and not cleaned.get('cta_label'):
            self.add_error('cta_label', 'Add the button text for this link.')
        if cleaned.get('cta_label') and not cleaned.get('cta_url'):
            self.add_error('cta_url', 'Add where the button should go.')
        starts, ends = cleaned.get('starts_at'), cleaned.get('ends_at')
        if starts and ends and ends <= starts:
            self.add_error('ends_at', 'This must be after the start time.')
        show_on = cleaned.get('show_on')
        if show_on in (Announcement.ShowOn.WEBSITE, Announcement.ShowOn.BOTH) and cleaned.get('audience') != Audience.ALL:
            self.add_error('audience', 'The website has no signed-in farmers or providers, so website announcements must be for everyone.')
        return cleaned


class BroadcastForm(TranslatedFieldsMixin, forms.ModelForm):
    translated_fields = ('title', 'message')

    class Meta:
        model = Broadcast
        fields = ['title', 'message', 'audience']
        labels = {'audience': 'Send to'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply(self.fields)
        self.fields['title'].widget.attrs['placeholder'] = 'e.g. Harvest season offer'
        self.add_translation_fields()
        # Push notifications show only the start of long text.
        for name in ('message', 'message_hi', 'message_mr'):
            self.fields[name].validators.append(MaxLengthValidator(BROADCAST_MESSAGE_LIMIT))
            self.fields[name].widget.attrs['maxlength'] = BROADCAST_MESSAGE_LIMIT
