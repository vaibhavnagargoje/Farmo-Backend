from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db.models import Q
from django.contrib.postgres.search import TrigramSimilarity

from services.models import Service, Category
from services.serializers import ServiceListSerializer, CategorySerializer

class SearchView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        query = request.query_params.get('q', '').strip()
        lang = request.query_params.get('lang', 'en')

        # ── Browse mode: no query → return all categories + recent services ──
        if not query:
            categories_qs = Category.objects.filter(is_active=True).order_by('name')

            services_qs = Service.objects.filter(
                status=Service.Status.ACTIVE,
                is_available=True,
                partner__is_available=True,
            ).select_related(
                'category', 'partner', 'partner__user'
            ).prefetch_related('images').order_by('-created_at')[:20]

            return Response({
                'query': '',
                'browse_mode': True,
                'categories': CategorySerializer(
                    categories_qs, many=True, context={'request': request}
                ).data,
                'services': ServiceListSerializer(
                    services_qs, many=True, context={'request': request}
                ).data,
                'total_services': services_qs.count() if hasattr(services_qs, 'count') else len(services_qs),
            })

        # ── Search mode: query provided ──

        # 1. Search Categories — English name + translated names (JSONField)
        categories_qs = Category.objects.filter(is_active=True).annotate(
            similarity=TrigramSimilarity('name', query)
        ).filter(
            Q(name__icontains=query) |
            Q(name_translations__icontains=query) |
            Q(similarity__gt=0.1)
        ).order_by('-similarity')[:10]

        # 2. Search Services — title, description, category name + translations
        base_qs = Service.objects.filter(
            status=Service.Status.ACTIVE,
            is_available=True,
            partner__is_available=True,
        ).select_related(
            'category', 'partner', 'partner__user'
        ).prefetch_related('images')

        services_qs = base_qs.annotate(
            title_similarity=TrigramSimilarity('title', query),
            desc_similarity=TrigramSimilarity('description', query)
        ).filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query) |
            Q(category__name_translations__icontains=query) |
            Q(title_similarity__gt=0.1) |
            Q(desc_similarity__gt=0.1)
        ).order_by('-title_similarity', '-desc_similarity')[:20]

        category_data = CategorySerializer(
            categories_qs, many=True, context={'request': request}
        ).data

        service_data = ServiceListSerializer(
            services_qs, many=True, context={'request': request}
        ).data

        return Response({
            'query': query,
            'browse_mode': False,
            'categories': category_data,
            'services': service_data,
            'total_services': len(service_data),
        })
