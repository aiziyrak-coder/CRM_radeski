# Import every module's models so SQLAlchemy metadata (and Alembic autogenerate) sees them.
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.diagnoses import models as diagnoses_models  # noqa: F401
from app.modules.patients import models as patients_models  # noqa: F401
from app.modules.users import models as users_models  # noqa: F401
