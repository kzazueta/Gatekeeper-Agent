-- Tabla de perfiles
CREATE TABLE IF NOT EXISTS perfiles (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(50) UNIQUE NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    tipo VARCHAR(50) NOT NULL,
    activo BOOLEAN DEFAULT TRUE
);

-- Tabla de logs de acceso
CREATE TABLE IF NOT EXISTS access_logs (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(50),
    nombre VARCHAR(100),
    tipo VARCHAR(50),
    puerta_id INTEGER DEFAULT 1,
    resultado VARCHAR(20),
    motivo VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de permisos por tipo de usuario
CREATE TABLE IF NOT EXISTS permisos_por_tipo (
    id SERIAL PRIMARY KEY,
    tipo_usuario VARCHAR(50) NOT NULL,
    puerta_id INTEGER NOT NULL,
    puede_acceder BOOLEAN DEFAULT TRUE,
    UNIQUE(tipo_usuario, puerta_id)
);

-- Perfiles de ejemplo
INSERT INTO perfiles (codigo, nombre, tipo) VALUES
('12345', 'Ana Perez', 'alumno'),
('67890', 'Dr. Juan Martinez', 'doctor'),
('54321', 'Carlos Lopez', 'admin'),
('11111', 'Maria Garcia', 'invitado'),
('10001', 'Luis Adrian Castaneda', 'alumno'),
('10002', 'Kevin David Zazueta', 'alumno'),
('10003', 'Carlos Alberto Becerra', 'alumno');

-- Permisos por tipo de usuario
INSERT INTO permisos_por_tipo (tipo_usuario, puerta_id, puede_acceder) VALUES
-- Entrada Principal (puerta 1): todos pueden acceder
('admin', 1, TRUE),
('doctor', 1, TRUE),
('alumno', 1, TRUE),
('invitado', 1, TRUE),

-- Laboratorio 1 (puerta 2): solo admin y doctor
('admin', 2, TRUE),
('doctor', 2, TRUE),
('alumno', 2, FALSE),
('invitado', 2, FALSE),

-- Oficina Direccion (puerta 3): solo admin
('admin', 3, TRUE),
('doctor', 3, FALSE),
('alumno', 3, FALSE),
('invitado', 3, FALSE),

-- Sala de Reuniones (puerta 4): admin, doctor y alumno
('admin', 4, TRUE),
('doctor', 4, TRUE),
('alumno', 4, TRUE),
('invitado', 4, FALSE);

-- Indices
CREATE INDEX idx_perfiles_codigo ON perfiles(codigo);
CREATE INDEX idx_logs_created ON access_logs(created_at);
CREATE INDEX idx_permisos_tipo_puerta ON permisos_por_tipo(tipo_usuario, puerta_id);