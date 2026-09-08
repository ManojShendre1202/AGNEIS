from django.urls import path

from . import views

urlpatterns = [
    path("tasks/", views.tasks_list_view, name="tasks_list"),
    # --- disabled for read-only server deploy (uncomment locally) ---
    # path("tasks/upload/", views.upload_task_view, name="upload_task"),
    path("tasks/<int:task_spec_id>/run/", views.run_stage_view, name="run_stage"),
    path("tasks/<int:task_spec_id>/verify/", views.verify_task_view, name="verify_task"),
    path("tasks/<int:task_spec_id>/sandbox/files/", views.sandbox_files_view, name="sandbox_files"),
    path("tasks/<int:task_spec_id>/sandbox/file/", views.sandbox_file_view, name="sandbox_file"),
    path("tasks/<int:task_spec_id>/", views.task_state_view, name="task_state"),
]
