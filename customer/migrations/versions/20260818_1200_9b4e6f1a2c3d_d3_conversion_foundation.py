"""D-3 conversion selection and immutable consent evidence.

Revision ID: 9b4e6f1a2c3d
Revises: 847937edd08e
Create Date: 2026-08-18 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "9b4e6f1a2c3d"
down_revision = "847937edd08e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing snapshots cannot be safely backfilled with evidence that was
    # never captured. Fail closed instead of guessing a payment method or
    # consent time. Customer routes remain production-unmounted at this phase.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM conversion_snapshot LIMIT 1) THEN
                RAISE EXCEPTION
                    'D-3 migration cannot infer evidence for existing conversion snapshots'
                    USING ERRCODE = 'object_not_in_prerequisite_state';
            END IF;
        END;
        $$;
        """
    )

    op.create_table(
        "conversion_selection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("plan_code", sa.String(length=40), nullable=False),
        sa.Column("price_krw", sa.Integer(), nullable=False),
        sa.Column("price_version", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'KRW'"), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("currency = 'KRW'", name=op.f("ck_conversion_selection_currency_krw")),
        sa.CheckConstraint("plan_code IN ('today_genie', 'keysuri_global', 'keysuri_korea', 'package_two', 'full_set')", name=op.f("ck_conversion_selection_plan_code_valid")),
        sa.CheckConstraint("price_krw > 0", name=op.f("ck_conversion_selection_price_positive")),
        sa.ForeignKeyConstraint(["account_id"], ["customer_account.id"], name=op.f("fk_conversion_selection_account_id_customer_account"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plan_code", "price_version"], ["plan_catalog.plan_code", "plan_catalog.price_version"], name="fk_conversion_selection_plan_catalog", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscription.id"], name=op.f("fk_conversion_selection_subscription_id_subscription"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversion_selection")),
        sa.UniqueConstraint("subscription_id", name="uq_conversion_selection_subscription_id"),
    )
    op.create_table(
        "conversion_selection_product",
        sa.Column("conversion_selection_id", sa.Uuid(), nullable=False),
        sa.Column("product_code", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["conversion_selection_id"], ["conversion_selection.id"], name=op.f("fk_conversion_selection_product_conversion_selection_id_conversion_selection"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_code"], ["product.code"], name=op.f("fk_conversion_selection_product_product_code_product"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("conversion_selection_id", "product_code", name=op.f("pk_conversion_selection_product")),
    )

    op.add_column("conversion_snapshot", sa.Column("selection_id", sa.Uuid(), nullable=False))
    op.add_column("conversion_snapshot", sa.Column("account_id", sa.Uuid(), nullable=False))
    op.add_column("conversion_snapshot", sa.Column("person_id", sa.Uuid(), nullable=False))
    op.add_column("conversion_snapshot", sa.Column("payment_method_id", sa.Uuid(), nullable=False))
    op.add_column("conversion_snapshot", sa.Column("first_charge_at", sa.DateTime(timezone=True), nullable=False))
    op.create_foreign_key(op.f("fk_conversion_snapshot_selection_id_conversion_selection"), "conversion_snapshot", "conversion_selection", ["selection_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(op.f("fk_conversion_snapshot_account_id_customer_account"), "conversion_snapshot", "customer_account", ["account_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(op.f("fk_conversion_snapshot_person_id_person_identity"), "conversion_snapshot", "person_identity", ["person_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(op.f("fk_conversion_snapshot_payment_method_id_payment_method"), "conversion_snapshot", "payment_method", ["payment_method_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint(op.f("uq_conversion_snapshot_selection_id"), "conversion_snapshot", ["selection_id"])
    op.create_check_constraint(op.f("ck_conversion_snapshot_first_charge_after_confirmation"), "conversion_snapshot", "first_charge_at > confirmed_at")

    op.execute(_SELECTION_CARDINALITY_FUNCTION)
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER conversion_selection_product_cardinality
        AFTER INSERT OR UPDATE OR DELETE ON conversion_selection_product
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION customer_check_conversion_selection_cardinality();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER conversion_selection_cardinality
        AFTER INSERT OR UPDATE OF plan_code ON conversion_selection
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION customer_check_conversion_selection_cardinality();
        """
    )
    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute("CREATE TRIGGER conversion_selection_consistent BEFORE INSERT OR UPDATE ON conversion_selection FOR EACH ROW EXECUTE FUNCTION customer_validate_conversion_selection();")
    op.execute("CREATE TRIGGER conversion_selection_product_consistent BEFORE INSERT OR UPDATE ON conversion_selection_product FOR EACH ROW EXECUTE FUNCTION customer_validate_conversion_product();")
    op.execute("CREATE TRIGGER conversion_snapshot_consistent BEFORE INSERT ON conversion_snapshot FOR EACH ROW EXECUTE FUNCTION customer_validate_conversion_snapshot();")
    op.execute("CREATE TRIGGER conversion_snapshot_product_consistent BEFORE INSERT OR UPDATE ON conversion_snapshot_product FOR EACH ROW EXECUTE FUNCTION customer_validate_conversion_product();")
    op.execute("CREATE TRIGGER conversion_snapshot_immutable BEFORE UPDATE OR DELETE ON conversion_snapshot FOR EACH ROW EXECUTE FUNCTION customer_protect_conversion_snapshot();")
    op.execute("CREATE TRIGGER conversion_snapshot_product_immutable BEFORE UPDATE OR DELETE ON conversion_snapshot_product FOR EACH ROW EXECUTE FUNCTION customer_protect_conversion_snapshot_product();")
    op.execute("CREATE TRIGGER conversion_selection_confirmed_immutable BEFORE UPDATE OR DELETE ON conversion_selection FOR EACH ROW EXECUTE FUNCTION customer_protect_confirmed_conversion_selection();")
    op.execute("CREATE TRIGGER conversion_selection_product_confirmed_immutable BEFORE UPDATE OR DELETE ON conversion_selection_product FOR EACH ROW EXECUTE FUNCTION customer_protect_confirmed_conversion_selection_product();")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS conversion_snapshot_product_consistent ON conversion_snapshot_product")
    op.execute("DROP TRIGGER IF EXISTS conversion_snapshot_consistent ON conversion_snapshot")
    op.execute("DROP TRIGGER IF EXISTS conversion_selection_product_consistent ON conversion_selection_product")
    op.execute("DROP TRIGGER IF EXISTS conversion_selection_consistent ON conversion_selection")
    op.execute("DROP TRIGGER IF EXISTS conversion_selection_product_confirmed_immutable ON conversion_selection_product")
    op.execute("DROP TRIGGER IF EXISTS conversion_selection_confirmed_immutable ON conversion_selection")
    op.execute("DROP TRIGGER IF EXISTS conversion_snapshot_product_immutable ON conversion_snapshot_product")
    op.execute("DROP TRIGGER IF EXISTS conversion_snapshot_immutable ON conversion_snapshot")
    op.execute("DROP FUNCTION IF EXISTS customer_protect_confirmed_conversion_selection_product()")
    op.execute("DROP FUNCTION IF EXISTS customer_protect_confirmed_conversion_selection()")
    op.execute("DROP FUNCTION IF EXISTS customer_protect_conversion_snapshot_product()")
    op.execute("DROP FUNCTION IF EXISTS customer_protect_conversion_snapshot()")
    op.execute("DROP FUNCTION IF EXISTS customer_validate_conversion_product()")
    op.execute("DROP FUNCTION IF EXISTS customer_validate_conversion_snapshot()")
    op.execute("DROP FUNCTION IF EXISTS customer_validate_conversion_selection()")
    op.execute("DROP TRIGGER IF EXISTS conversion_selection_cardinality ON conversion_selection")
    op.execute("DROP TRIGGER IF EXISTS conversion_selection_product_cardinality ON conversion_selection_product")
    op.execute("DROP FUNCTION IF EXISTS customer_check_conversion_selection_cardinality()")
    op.drop_constraint(op.f("ck_conversion_snapshot_first_charge_after_confirmation"), "conversion_snapshot", type_="check")
    op.drop_constraint(op.f("uq_conversion_snapshot_selection_id"), "conversion_snapshot", type_="unique")
    op.drop_constraint(op.f("fk_conversion_snapshot_payment_method_id_payment_method"), "conversion_snapshot", type_="foreignkey")
    op.drop_constraint(op.f("fk_conversion_snapshot_person_id_person_identity"), "conversion_snapshot", type_="foreignkey")
    op.drop_constraint(op.f("fk_conversion_snapshot_account_id_customer_account"), "conversion_snapshot", type_="foreignkey")
    op.drop_constraint(op.f("fk_conversion_snapshot_selection_id_conversion_selection"), "conversion_snapshot", type_="foreignkey")
    op.drop_column("conversion_snapshot", "first_charge_at")
    op.drop_column("conversion_snapshot", "payment_method_id")
    op.drop_column("conversion_snapshot", "person_id")
    op.drop_column("conversion_snapshot", "account_id")
    op.drop_column("conversion_snapshot", "selection_id")
    op.drop_table("conversion_selection_product")
    op.drop_table("conversion_selection")


_SELECTION_CARDINALITY_FUNCTION = """
CREATE OR REPLACE FUNCTION customer_check_conversion_selection_cardinality()
RETURNS TRIGGER AS $$
DECLARE
    target_id uuid;
    target_plan varchar(40);
    expected_count smallint;
    actual_count smallint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_id := OLD.conversion_selection_id;
    ELSIF TG_TABLE_NAME = 'conversion_selection' THEN
        target_id := NEW.id;
    ELSE
        target_id := NEW.conversion_selection_id;
    END IF;
    SELECT plan_code INTO target_plan FROM conversion_selection WHERE id = target_id;
    IF NOT FOUND THEN RETURN NULL; END IF;
    expected_count := CASE WHEN target_plan = 'full_set' THEN 3 WHEN target_plan = 'package_two' THEN 2 ELSE 1 END;
    SELECT count(DISTINCT product_code) INTO actual_count FROM conversion_selection_product WHERE conversion_selection_id = target_id;
    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'conversion selection % plan % requires exactly % product(s), found %', target_id, target_plan, expected_count, actual_count USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION customer_validate_conversion_selection()
RETURNS TRIGGER AS $$
DECLARE
    subscription_account uuid;
BEGIN
    SELECT account_id INTO subscription_account FROM subscription WHERE id = NEW.subscription_id;
    IF NOT FOUND OR subscription_account IS DISTINCT FROM NEW.account_id THEN
        RAISE EXCEPTION 'conversion selection account/subscription mismatch' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION customer_validate_conversion_snapshot()
RETURNS TRIGGER AS $$
DECLARE
    subscription_account uuid;
    subscription_trial_end timestamptz;
    selection_row conversion_selection%ROWTYPE;
    account_person uuid;
    method_account uuid;
BEGIN
    SELECT account_id, trial_end_at INTO subscription_account, subscription_trial_end
    FROM subscription WHERE id = NEW.subscription_id;
    SELECT * INTO selection_row FROM conversion_selection WHERE id = NEW.selection_id;
    SELECT person_id INTO account_person FROM customer_account WHERE id = NEW.account_id;
    SELECT account_id INTO method_account FROM payment_method WHERE id = NEW.payment_method_id;
    IF subscription_account IS DISTINCT FROM NEW.account_id
       OR selection_row.account_id IS DISTINCT FROM NEW.account_id
       OR selection_row.subscription_id IS DISTINCT FROM NEW.subscription_id
       OR account_person IS DISTINCT FROM NEW.person_id
       OR method_account IS DISTINCT FROM NEW.account_id
       OR selection_row.plan_code IS DISTINCT FROM NEW.plan_code
       OR selection_row.price_krw IS DISTINCT FROM NEW.price_krw
       OR selection_row.price_version IS DISTINCT FROM NEW.price_version
       OR selection_row.currency IS DISTINCT FROM NEW.currency
       OR subscription_trial_end IS DISTINCT FROM NEW.first_charge_at
       OR NEW.status <> 'pending' THEN
        RAISE EXCEPTION 'conversion snapshot evidence is inconsistent' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION customer_validate_conversion_product()
RETURNS TRIGGER AS $$
DECLARE
    target_plan varchar(40);
BEGIN
    IF TG_TABLE_NAME = 'conversion_selection_product' THEN
        SELECT plan_code INTO target_plan FROM conversion_selection WHERE id = NEW.conversion_selection_id;
    ELSE
        SELECT plan_code INTO target_plan FROM conversion_snapshot WHERE id = NEW.conversion_snapshot_id;
    END IF;
    IF target_plan IN ('today_genie', 'keysuri_global', 'keysuri_korea')
       AND NEW.product_code <> target_plan THEN
        RAISE EXCEPTION 'single-product conversion plan/product mismatch' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION customer_protect_conversion_snapshot()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'conversion snapshots are immutable evidence' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.selection_id IS DISTINCT FROM NEW.selection_id
       OR OLD.account_id IS DISTINCT FROM NEW.account_id
       OR OLD.person_id IS DISTINCT FROM NEW.person_id
       OR OLD.subscription_id IS DISTINCT FROM NEW.subscription_id
       OR OLD.payment_method_id IS DISTINCT FROM NEW.payment_method_id
       OR OLD.plan_code IS DISTINCT FROM NEW.plan_code
       OR OLD.price_krw IS DISTINCT FROM NEW.price_krw
       OR OLD.price_version IS DISTINCT FROM NEW.price_version
       OR OLD.currency IS DISTINCT FROM NEW.currency
       OR OLD.confirmed_at IS DISTINCT FROM NEW.confirmed_at
       OR OLD.first_charge_at IS DISTINCT FROM NEW.first_charge_at THEN
        RAISE EXCEPTION 'confirmed conversion evidence may not be rewritten' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status <> NEW.status AND NOT (OLD.status = 'pending' AND NEW.status IN ('applied', 'abandoned')) THEN
        RAISE EXCEPTION 'invalid conversion snapshot status transition' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION customer_protect_conversion_snapshot_product()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'conversion snapshot products are immutable evidence' USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION customer_protect_confirmed_conversion_selection()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM conversion_snapshot WHERE selection_id = OLD.id) THEN
        RAISE EXCEPTION 'confirmed conversion selection may not be changed' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION customer_protect_confirmed_conversion_selection_product()
RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM conversion_snapshot WHERE selection_id = OLD.conversion_selection_id) THEN
        RAISE EXCEPTION 'confirmed conversion selection products may not be changed' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
"""
