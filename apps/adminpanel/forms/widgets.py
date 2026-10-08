"""Shared admin panel form widget styling."""

from django import forms


TEXT_ATTRS = {"class": "form-input"}


TEXTAREA_ATTRS = {"class": "form-input", "rows": 3}


FILE_ATTRS = {"class": "form-input"}


SELECT_ATTRS = {"class": "form-input"}


def _apply(fields, mapping=None):
    """Apply standard widget attrs to every field in a ModelForm."""
    if mapping is None:
        mapping = {}
    for name, field in fields.items():
        if name in mapping:
            field.widget.attrs.update(mapping[name])
        elif isinstance(field.widget, forms.Textarea):
            field.widget.attrs.update(TEXTAREA_ATTRS)
        elif isinstance(field.widget, (forms.ClearableFileInput, forms.FileInput)):
            field.widget.attrs.update(FILE_ATTRS)
        elif isinstance(field.widget, forms.Select):
            field.widget.attrs.update(SELECT_ATTRS)
        elif isinstance(field.widget, forms.CheckboxInput):
            pass  # handled by toggle UI in template
        else:
            field.widget.attrs.update(TEXT_ATTRS)
