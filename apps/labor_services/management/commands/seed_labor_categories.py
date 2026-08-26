from django.core.management.base import BaseCommand
from labor_services.models import LaborCategory, LaborServiceType

class Command(BaseCommand):
    help = 'Seeds initial labor categories and service types'

    def handle(self, *args, **kwargs):
        categories = [
            {
                'name': 'Farming',
                'slug': 'farming',
                'name_translations': {"en": "Farming", "mr": "शेतीकामे", "hi": "खेती के काम"},
                'order': 1,
                'service_types': [
                    {'name': 'Farming Work', 'slug': 'farming-work', 'name_translations': {"en": "Farming Work", "mr": "शेतीकाम", "hi": "खेती का काम"}, 'order': 1},
                    {'name': 'Weeding', 'slug': 'weeding', 'name_translations': {"en": "Weeding", "mr": "खुरपणी", "hi": "निराई"}, 'order': 2},
                    {'name': 'Sowing', 'slug': 'sowing', 'name_translations': {"en": "Sowing", "mr": "पेरणी", "hi": "बुवाई"}, 'order': 3},
                    {'name': 'Harvester', 'slug': 'harvester', 'name_translations': {"en": "Harvester", "mr": "कापणी कामगार", "hi": "फसल काटने वाला"}, 'order': 4},
                    {'name': 'Plougher', 'slug': 'plougher', 'name_translations': {"en": "Plougher", "mr": "नांगरणी", "hi": "खेत जोतने वाला"}, 'order': 5},
                    {'name': 'Spraying', 'slug': 'spraying', 'name_translations': {"en": "Spraying", "mr": "फवारणी", "hi": "छिड़काव"}, 'order': 6},
                ]
            },
            {
                'name': 'Construction',
                'slug': 'construction',
                'name_translations': {"en": "Construction", "mr": "बांधकाम", "hi": "निर्माण"},
                'order': 2,
                'service_types': [
                    {'name': 'Mason', 'slug': 'mason', 'name_translations': {"en": "Mason", "mr": "गवंडी", "hi": "राजमिस्त्री"}, 'order': 1},
                    {'name': 'Helper', 'slug': 'helper', 'name_translations': {"en": "Helper", "mr": "मदतनीस", "hi": "हेल्पर"}, 'order': 2},
                    {'name': 'Loader', 'slug': 'loader', 'name_translations': {"en": "Loader", "mr": "हमाल", "hi": "हम्माल"}, 'order': 3},
                ]
            },
            {
                'name': 'Skilled Trade',
                'slug': 'skilled-trade',
                'name_translations': {"en": "Skilled Trade", "mr": "कुशल कामगार", "hi": "कुशल श्रमिक"},
                'order': 3,
                'service_types': [
                    {'name': 'Plumber', 'slug': 'plumber', 'name_translations': {"en": "Plumber", "mr": "प्लंबर", "hi": "प्लंबर"}, 'order': 1},
                    {'name': 'Painter', 'slug': 'painter', 'name_translations': {"en": "Painter", "mr": "पेंटर", "hi": "पेंटर"}, 'order': 2},
                    {'name': 'Welder', 'slug': 'welder', 'name_translations': {"en": "Welder", "mr": "वेल्डर", "hi": "वेल्डर"}, 'order': 3},
                    {'name': 'Carpenter', 'slug': 'carpenter', 'name_translations': {"en": "Carpenter", "mr": "सुतार", "hi": "बढ़ई"}, 'order': 4},
                    {'name': 'Electrician', 'slug': 'electrician', 'name_translations': {"en": "Electrician", "mr": "इलेक्ट्रिशियन", "hi": "इलेक्ट्रीशियन"}, 'order': 5},
                ]
            },
            {
                'name': 'Transport',
                'slug': 'transport',
                'name_translations': {"en": "Transport", "mr": "वाहतूक", "hi": "परिवहन"},
                'order': 4,
                'service_types': [
                    {'name': 'Driver', 'slug': 'driver', 'name_translations': {"en": "Driver", "mr": "चालक", "hi": "ड्राइवर"}, 'order': 1},
                ]
            },
        ]

        for cat_data in categories:
            service_types = cat_data.pop('service_types')
            category, created = LaborCategory.objects.get_or_create(
                slug=cat_data['slug'],
                defaults=cat_data
            )
            if not created:
                category.name = cat_data['name']
                category.name_translations = cat_data['name_translations']
                category.order = cat_data['order']
                category.save()
            
            for st_data in service_types:
                service_type, st_created = LaborServiceType.objects.get_or_create(
                    slug=st_data['slug'],
                    defaults={**st_data, 'category': category}
                )
                if not st_created:
                    service_type.name = st_data['name']
                    service_type.name_translations = st_data['name_translations']
                    service_type.order = st_data['order']
                    service_type.category = category
                    service_type.save()
        
        self.stdout.write(self.style.SUCCESS('Successfully seeded labor categories and service types.'))
