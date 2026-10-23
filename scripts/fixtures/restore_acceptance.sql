-- Synthetic recovery fixture, not the DIMAX application schema or real records.
CREATE TYPE door_state AS ENUM ('PENDING', 'INSTALLED');
CREATE TABLE companies (id integer PRIMARY KEY, name text NOT NULL);
CREATE TABLE projects (id serial PRIMARY KEY, company_id integer REFERENCES companies(id), name text NOT NULL);
CREATE TABLE doors (id bigserial PRIMARY KEY, project_id integer NOT NULL REFERENCES projects(id),
                    unit_label text NOT NULL UNIQUE, status door_state NOT NULL);
CREATE TABLE completed_work (id bigserial PRIMARY KEY, door_id bigint NOT NULL REFERENCES doors(id),
                             event_key text NOT NULL UNIQUE, amount numeric(12,2) NOT NULL CHECK (amount <> 0),
                             occurred_at timestamptz NOT NULL);
CREATE TABLE journals (id serial PRIMARY KEY, project_id integer NOT NULL REFERENCES projects(id),
                       status text NOT NULL, object_key text NOT NULL, signature_bytes bytea NOT NULL);
CREATE TABLE outbox_messages (id serial PRIMARY KEY, journal_id integer REFERENCES journals(id),
                              status text NOT NULL, attempts integer NOT NULL CHECK (attempts >= 0),
                              payload jsonb NOT NULL);
CREATE INDEX pending_mail ON outbox_messages(status) WHERE status='PENDING';
INSERT INTO companies VALUES (1, 'Synthetic A'), (2, 'Synthetic B');
INSERT INTO projects(company_id,name) VALUES (1, U&'\05D1\05E0\05D9\05D9\05DF'), (2, U&'\041E\0431\044A\0435\043A\0442');
INSERT INTO doors(project_id,unit_label,status) VALUES (1,'TEST-A-101','INSTALLED'), (2,'TEST-B-201','PENDING');
INSERT INTO completed_work(door_id,event_key,amount,occurred_at) VALUES
    (1,'synthetic-installation',9.01,'2026-10-10 09:00:00+03'),
    (1,'synthetic-extra-work',13.50,'2026-10-10 09:30:00+03'),
    (1,'synthetic-correction',-1.01,'2026-10-11 09:00:00+03');
INSERT INTO journals(project_id,status,object_key,signature_bytes) VALUES
    (1,'SIGNED','synthetic/journal.pdf',decode('0001ff1020','hex'));
INSERT INTO outbox_messages(journal_id,status,attempts,payload) VALUES
    (1,'PENDING',2,'{"to_email":"test@dimax.example","kind":"SIGNED_JOURNAL","version":1}'),
    (1,'SENT',1,'{"to_email":"test@dimax.example","kind":"SYNTHETIC_PREVIOUS"}');
