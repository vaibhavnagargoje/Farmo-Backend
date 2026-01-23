# apps/services/views.py
from rest_framework import status, generics, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from django.shortcuts import get_object_or_404

from .models import Category, Service, ServiceImage
from .serializers import (
    CategorySerializer,
    ServiceListSerializer,
    ServiceDetailSerializer,
    ServiceCreateSerializer,
    ServiceUpdateSerializer,
    ServiceImageSerializer
)


# --- Category Views ---
class CategoryListView(generics.ListAPIView):
    """
    GET: List all active categories.
    """
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = []  # Public


# --- Service Views (Public) ---
class ServiceListView(generics.ListAPIView):
    """
    GET: List all active services with filters and search.
    Publicly accessible for customers browsing.
    """
    serializer_class = ServiceListSerializer
    permission_classes = []  # Public
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description', 'partner__business_name']
    ordering_fields = ['price', 'created_at', 'partner__rating']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = Service.objects.filter(status=Service.Status.ACTIVE, is_available=True)
        
        # Manual filtering for category
        category_slug = self.request.query_params.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        
        price_unit = self.request.query_params.get('price_unit')
        if price_unit:
            queryset = queryset.filter(price_unit=price_unit.upper())
        
        return queryset


class ServiceDetailView(generics.RetrieveAPIView):
    """
    GET: View details of a single service.
    """
    queryset = Service.objects.filter(status=Service.Status.ACTIVE)
    serializer_class = ServiceDetailSerializer
    permission_classes = []  # Public
    lookup_field = 'id'


# --- Service Views (Partner Only) ---
class PartnerServiceListView(generics.ListCreateAPIView):
    """
    GET: List all services owned by the logged-in partner.
    POST: Create a new service.
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ServiceCreateSerializer
        return ServiceListSerializer

    def get_queryset(self):
        # Only return services belonging to this partner
        if hasattr(self.request.user, 'partner_profile'):
            return Service.objects.filter(partner=self.request.user.partner_profile)
        return Service.objects.none()

    def create(self, request, *args, **kwargs):
        # Check if user is a partner
        if not hasattr(request.user, 'partner_profile'):
            return Response(
                {"error": "You must be a registered Partner to create services."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            service = serializer.save()
            return Response({
                "message": "Service created successfully.",
                "service": ServiceDetailSerializer(service, context={'request': request}).data
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PartnerServiceDetailView(APIView):
    """
    GET: View own service details.
    PATCH: Update own service.
    DELETE: Delete own service.
    """
    permission_classes = [IsAuthenticated]

    def get_service(self, request, service_id):
        """Helper to get service owned by current user."""
        if not hasattr(request.user, 'partner_profile'):
            return None
        return get_object_or_404(
            Service,
            id=service_id,
            partner=request.user.partner_profile
        )

    def get(self, request, service_id):
        service = self.get_service(request, service_id)
        if not service:
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = ServiceDetailSerializer(service, context={'request': request})
        return Response(serializer.data)

    def patch(self, request, service_id):
        service = self.get_service(request, service_id)
        if not service:
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = ServiceUpdateSerializer(service, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Service updated successfully.",
                "service": ServiceDetailSerializer(service, context={'request': request}).data
            })
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, service_id):
        service = self.get_service(request, service_id)
        if not service:
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        
        service.delete()
        return Response({"message": "Service deleted successfully."}, status=status.HTTP_204_NO_CONTENT)


class ServiceImageUploadView(APIView):
    """
    POST: Upload additional images to a service.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, service_id):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        
        service = get_object_or_404(
            Service,
            id=service_id,
            partner=request.user.partner_profile
        )
        
        images = request.FILES.getlist('images')
        if not images:
            return Response({"error": "No images provided."}, status=status.HTTP_400_BAD_REQUEST)
        
        created_images = []
        for image in images:
            img = ServiceImage.objects.create(service=service, image=image)
            created_images.append(ServiceImageSerializer(img).data)
        
        return Response({
            "message": f"{len(created_images)} image(s) uploaded successfully.",
            "images": created_images
        }, status=status.HTTP_201_CREATED)


class ServiceImageDeleteView(APIView):
    """
    DELETE: Remove an image from a service.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, service_id, image_id):
        if not hasattr(request.user, 'partner_profile'):
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        
        image = get_object_or_404(
            ServiceImage,
            id=image_id,
            service_id=service_id,
            service__partner=request.user.partner_profile
        )
        
        image.delete()
        return Response({"message": "Image deleted successfully."}, status=status.HTTP_204_NO_CONTENT)
