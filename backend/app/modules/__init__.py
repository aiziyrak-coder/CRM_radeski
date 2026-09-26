# Import every module's models so SQLAlchemy metadata (and Alembic autogenerate) sees them.
from app.modules.ai import models as ai_models  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.campaigns import models as campaigns_models  # noqa: F401
from app.modules.catalog import models as catalog_models  # noqa: F401
from app.modules.diagnoses import models as diagnoses_models  # noqa: F401
from app.modules.leads import models as leads_models  # noqa: F401
from app.modules.messaging import models as messaging_models  # noqa: F401
from app.modules.patients import models as patients_models  # noqa: F401
from app.modules.scheduling import models as scheduling_models  # noqa: F401
from app.modules.scripts import models as scripts_models  # noqa: F401
from app.modules.tasks import models as tasks_models  # noqa: F401
from app.modules.telephony import models as telephony_models  # noqa: F401
from app.modules.users import models as users_models  # noqa: F401
