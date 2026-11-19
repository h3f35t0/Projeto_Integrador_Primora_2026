from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from importacao import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(
        template_name="importacao/login.html",
        redirect_authenticated_user=True
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("importacao/", include("importacao.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
