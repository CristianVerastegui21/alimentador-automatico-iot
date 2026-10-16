-- Ejecutar en Supabase SQL Editor. Crear/actualizar tablas sin borrar datos.
create table if not exists public.dispositivos (
 id bigserial primary key, nombre varchar(100) not null,
 codigo varchar(100) unique not null, nivel_alimento integer,
 distancia_cm numeric(8,2), estado varchar(50) default 'desconectado',
 ultima_conexion timestamptz, creado_en timestamptz default now()
);
create table if not exists public.horarios (
 id bigserial primary key, dispositivo_id bigint not null references public.dispositivos(id),
 nombre varchar(100) not null, hora time not null, activo boolean default true,
 creado_en timestamptz default now()
);
create table if not exists public.ordenes (
 id bigserial primary key, dispositivo_id bigint not null references public.dispositivos(id),
 tipo varchar(20) not null, estado varchar(20) default 'pendiente',
 creado_en timestamptz default now(), ejecutado_en timestamptz
);
create table if not exists public.historial (
 id bigserial primary key, dispositivo_id bigint not null references public.dispositivos(id),
 tipo varchar(20) not null, resultado varchar(50) not null, fecha timestamptz default now()
);
insert into public.dispositivos(nombre,codigo) values ('Alimentador principal','ESP32-001')
on conflict (codigo) do nothing;

-- Protección de concurrencia para una sola orden activa por dispositivo.
create unique index if not exists uq_orden_activa_dispositivo
on public.ordenes(dispositivo_id) where estado in ('pendiente','procesando');

-- Los RPC son SECURITY INVOKER; Flask debe usar una clave de servidor con permisos.
create or replace function public.encolar_alimentacion(p_dispositivo_id bigint)
returns bigint language plpgsql security invoker set search_path = '' as $$
declare v_id bigint;
begin
  insert into public.ordenes(dispositivo_id,tipo,estado)
  values (p_dispositivo_id,'manual','pendiente') returning id into v_id;
  return v_id;
exception when unique_violation then
  return null;
end $$;

create or replace function public.tomar_orden_alimentacion(p_dispositivo_id bigint)
returns bigint language plpgsql security invoker set search_path = '' as $$
declare v_id bigint;
begin
  select id into v_id from public.ordenes
  where dispositivo_id=p_dispositivo_id and estado='pendiente'
  order by id for update skip locked limit 1;
  if v_id is null then return null; end if;
  update public.ordenes set estado='procesando' where id=v_id and estado='pendiente';
  return v_id;
end $$;

-- Solo el backend debe poder ejecutar estas funciones (no el navegador).
revoke execute on function public.encolar_alimentacion(bigint) from public, anon, authenticated;
revoke execute on function public.tomar_orden_alimentacion(bigint) from public, anon, authenticated;
grant execute on function public.encolar_alimentacion(bigint) to service_role;
grant execute on function public.tomar_orden_alimentacion(bigint) to service_role;

-- Protección para uso con clave service_role exclusivamente desde Flask.
alter table public.dispositivos enable row level security;
alter table public.horarios enable row level security;
alter table public.ordenes enable row level security;
alter table public.historial enable row level security;
