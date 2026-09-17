
from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from extensions import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app)  
    db.init_app(app)

    from routes import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    with app.app_context():
        import models  
        db.create_all()
        _seed_admin(app)

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "trekking-management-api"})

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(500)
    def server_error(_e):
        return jsonify({"error": "Internal server error"}), 500

    return app


def _seed_admin(app):

    from models import User, UserRole, UserStatus

    existing_admin = User.query.filter_by(role=UserRole.ADMIN.value).first()
    if existing_admin:
        return

    admin = User(
        name=app.config["ADMIN_NAME"],
        email=app.config["ADMIN_EMAIL"],
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    admin.set_password(app.config["ADMIN_PASSWORD"])
    db.session.add(admin)
    db.session.commit()
    print(f"[SEED] Admin account created -> email: {admin.email} / password: {app.config['ADMIN_PASSWORD']}")


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)