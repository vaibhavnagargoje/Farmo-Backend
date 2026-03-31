from django import forms

from partners.models import LaborDetails, PartnerProfile
from users.models import User


MARATHI_SKILLS = [
    "गवंडी",
    "मदतनीस",
    "कापणी कामगार",
    "नांगरणी",
    "खुरपणी",
    "फवारणी",
    "हमाल",
    "चालक",
    "सुतार",
    "पेंटर",
    "इलेक्ट्रिशियन",
    "प्लंबर",
    "शेतीकाम",
    "पेरणी",
]


class AgentUserRegistrationForm(forms.Form):
    phone_number = forms.CharField(
        max_length=15,
        label="मोबाईल नंबर",
        error_messages={"required": "मोबाईल नंबर आवश्यक आहे."},
    )
    email = forms.EmailField(
        required=False,
        label="ईमेल (ऐच्छिक)",
        error_messages={"invalid": "कृपया वैध ईमेल पत्ता टाका."},
    )
    full_name = forms.CharField(
        max_length=255,
        label="पूर्ण नाव",
        error_messages={"required": "पूर्ण नाव आवश्यक आहे."},
    )
    address = forms.CharField(
        label="पत्ता",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=True,
        error_messages={"required": "पत्ता आवश्यक आहे."},
    )
    latitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=True,
        label="अक्षांश",
        error_messages={
            "required": "अक्षांश आवश्यक आहे.",
            "invalid": "वैध अक्षांश टाका.",
        },
    )
    longitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        required=True,
        label="रेखांश",
        error_messages={
            "required": "रेखांश आवश्यक आहे.",
            "invalid": "वैध रेखांश टाका.",
        },
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field_classes = (
            "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 "
            "text-sm text-slate-900 focus:border-emerald-500 focus:outline-none "
            "focus:ring-2 focus:ring-emerald-200"
        )

        self.fields["phone_number"].widget.attrs.update(
            {
                "class": field_classes,
                "placeholder": "मोबाईल नंबर टाका",
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "class": field_classes,
                "placeholder": "example@email.com",
            }
        )
        self.fields["full_name"].widget.attrs.update(
            {
                "class": field_classes,
                "placeholder": "पूर्ण नाव टाका",
            }
        )
        self.fields["address"].widget.attrs.update(
            {
                "class": field_classes,
                "placeholder": "गाव / तालुका / जिल्हा",
            }
        )
        self.fields["latitude"].widget.attrs.update(
            {
                "class": field_classes,
                "placeholder": "18.520430",
            }
        )
        self.fields["longitude"].widget.attrs.update(
            {
                "class": field_classes,
                "placeholder": "73.856744",
            }
        )

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if User.objects.filter(phone_number=phone_number).exists():
            raise forms.ValidationError("हा मोबाईल नंबर आधीच नोंदणीकृत आहे.")
        return phone_number

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email and User.objects.filter(email=email).exists():
            raise forms.ValidationError("हा ईमेल आधीच नोंदणीकृत आहे.")
        return email


class WorkerPartnerProfileForm(forms.ModelForm):
    class Meta:
        model = PartnerProfile
        fields = ["aadhar_card_front", "aadhar_card_back", "pan_card"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        file_input_classes = (
            "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 "
            "text-sm text-slate-900 file:mr-3 file:rounded-md file:border-0 "
            "file:bg-slate-100 file:px-3 file:py-2 file:text-slate-700"
        )

        for name in ("aadhar_card_front", "aadhar_card_back", "pan_card"):
            self.fields[name].required = False
            self.fields[name].widget.attrs.update({"class": file_input_classes})

    def clean(self):
        cleaned_data = super().clean()

        has_aadhar_front = bool(
            cleaned_data.get("aadhar_card_front")
            or (self.instance and getattr(self.instance, "aadhar_card_front", None))
        )
        has_aadhar_back = bool(
            cleaned_data.get("aadhar_card_back")
            or (self.instance and getattr(self.instance, "aadhar_card_back", None))
        )
        has_pan = bool(
            cleaned_data.get("pan_card")
            or (self.instance and getattr(self.instance, "pan_card", None))
        )

        has_full_aadhar = has_aadhar_front and has_aadhar_back

        if not has_pan and not has_full_aadhar:
            raise forms.ValidationError(
                "आधार कार्ड (समोर आणि मागील बाजू) किंवा पॅन कार्ड यापैकी किमान एक दस्तऐवज आवश्यक आहे."
            )

        return cleaned_data


class LaborDetailsForm(forms.ModelForm):
    skills = forms.MultipleChoiceField(
        choices=[(skill, skill) for skill in MARATHI_SKILLS],
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="कौशल्ये",
        error_messages={"required": "किमान एक कौशल्य निवडा."},
    )
    is_migrant_worker = forms.ChoiceField(
        choices=(("yes", "होय"), ("no", "नाही")),
        widget=forms.RadioSelect,
        label="स्थलांतरित कामगार आहे का?",
        required=True,
        error_messages={"required": "कृपया पर्याय निवडा."},
    )

    class Meta:
        model = LaborDetails
        fields = ["daily_wage_estimate", "skills", "skill_card_photo", "is_migrant_worker"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field_classes = (
            "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 "
            "text-sm text-slate-900 focus:border-emerald-500 focus:outline-none "
            "focus:ring-2 focus:ring-emerald-200"
        )
        file_input_classes = (
            "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 "
            "text-sm text-slate-900 file:mr-3 file:rounded-md file:border-0 "
            "file:bg-slate-100 file:px-3 file:py-2 file:text-slate-700"
        )

        self.fields["daily_wage_estimate"].required = True
        self.fields["daily_wage_estimate"].widget.attrs.update(
            {
                "class": field_classes,
                "placeholder": "उदा. ८००",
            }
        )
        self.fields["daily_wage_estimate"].label = "दैनिक मजुरी"
        self.fields["daily_wage_estimate"].error_messages.update(
            {
                "required": "दैनिक मजुरी आवश्यक आहे.",
                "invalid": "वैध रक्कम टाका.",
            }
        )

        self.fields["skills"].widget.attrs.update({"class": "peer sr-only"})

        self.fields["skill_card_photo"].required = False
        self.fields["skill_card_photo"].widget.attrs.update({"class": file_input_classes})
        self.fields["skill_card_photo"].label = "कौशल्य कार्ड फोटो (ऐच्छिक)"

        self.fields["is_migrant_worker"].widget.attrs.update({"class": "mt-2 space-y-2"})

        instance = kwargs.get("instance")
        if instance is not None and instance.pk:
            self.initial["is_migrant_worker"] = "yes" if instance.is_migrant_worker else "no"
            selected_skills = [skill.strip() for skill in (instance.skills or "").split(",") if skill.strip()]
            self.initial["skills"] = selected_skills

    def clean_skills(self):
        selected_skills = self.cleaned_data.get("skills") or []
        if not selected_skills:
            raise forms.ValidationError("किमान एक कौशल्य निवडा.")
        return ", ".join(selected_skills)

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["is_migrant_worker"] = cleaned_data.get("is_migrant_worker") == "yes"
        return cleaned_data
