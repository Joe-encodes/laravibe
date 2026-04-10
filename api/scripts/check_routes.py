from api.main import app

for route in app.routes:
    # Get methods and path
    methods = getattr(route, "methods", None)
    path = getattr(route, "path", None)
    if path:
        print(f"{methods} {path}")
