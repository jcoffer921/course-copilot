from django import forms

from .models import ContactRequest


class ContactRequestForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput, label="Leave this field empty")

    class Meta:
        model = ContactRequest
        fields = ("name", "email", "topic", "subject", "message")
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Your name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "you@example.com"}),
            "subject": forms.TextInput(attrs={"placeholder": "A short summary"}),
            "message": forms.Textarea(attrs={"rows": 7, "placeholder": "Tell us what you need help with. Please do not include passwords or highly sensitive information."}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("website"):
            raise forms.ValidationError("Unable to submit this request.")
        return cleaned
