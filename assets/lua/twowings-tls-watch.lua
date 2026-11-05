-- 2Wings: notice servers that reject a desynced TLS handshake.
--
-- When a strategy's fake or seqovl part reaches the server, the server cannot
-- parse the ClientHello and answers with one of:
--   * a plaintext fatal TLS alert (record 15 03 xx 00 02 02);
--   * a plain "HTTP/1.x 400" — e.g. Tengine (aliexpress.ru) treats the garbage as HTTP.
-- The browser shows ERR_SSL_PROTOCOL_ERROR. An ISP's DPI never answers a TLS
-- connection like that: it resets or drops it. winws2 diverts only such
-- inbound packets (--wf-raw-part), so this runs on a handful of packets.
--
-- twowings_tls_watch sits first in every profile and appends one line per server
-- to tls-alerts.txt in the --writable directory:
--   d <hostname> <ip> <code>   the profile excludes by hostlist-exclude
--   i - <ip> <code>            the profile excludes by ipset only (arg exclude=ip)
-- <code> is the TLS alert description, or 0 for an HTTP reply.
-- The 2Wings daemon moves those into the user's exclude lists; winws2 rereads
-- list files on change. Requires zapret-lib.lua (host_ip, writable_file_name).

local twowings_reported = {}

local function twowings_fatal_alert(payload)
	if #payload >= 7
		and string.byte(payload, 1) == 0x15 -- alert record
		and string.byte(payload, 2) == 0x03 -- TLS version major
		and string.byte(payload, 4) == 0x00 and string.byte(payload, 5) == 0x02 -- plaintext, 2 bytes
		and string.byte(payload, 6) == 0x02 -- level: fatal
	then
		return string.byte(payload, 7)
	end
	return nil
end

-- What the server said instead of a ServerHello, or nil when it is not a rejection.
local function twowings_rejection(payload, track)
	local alert = twowings_fatal_alert(payload)
	if alert then return alert end
	-- HTTP only counts on a connection that started with our TLS ClientHello.
	if string.sub(payload, 1, 5) == "HTTP/" and track and track.l7proto == "tls" then
		return 0
	end
	return nil
end

function twowings_tls_watch(ctx, desync)
	if desync.outgoing then return end
	local payload = desync.dis.payload
	if not payload or #payload < 5 then return end
	local track = desync.track
	local code = twowings_rejection(payload, track)
	if not code then return end

	local ip = host_ip(desync)
	local host = track and not track.hostname_is_ip and track.hostname or nil
	local entry
	if host and desync.arg.exclude ~= "ip" then
		entry = "d " .. host .. " " .. (ip or "-")
	elseif ip then
		entry = "i - " .. ip
	else
		return
	end
	if twowings_reported[entry] then return end
	twowings_reported[entry] = true

	local f = io.open(writable_file_name("tls-alerts.txt"), "a")
	if f then
		f:write(entry .. " " .. code .. "\n")
		f:close()
	end
	DLOG("twowings_tls_watch: server rejected TLS (" .. code .. "): " .. entry)
end
