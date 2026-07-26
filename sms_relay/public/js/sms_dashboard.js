frappe.provide("sms_relay");

frappe.pages["sms-dashboard"].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "SMS Dashboard",
        single_column: true
    });

    sms_relay.dashboard = new sms_relay.Dashboard(page);
};

sms_relay.Dashboard = class Dashboard {
    constructor(page) {
        this.page = page;
        this.make();
        this.refresh();
        setInterval(() => this.refresh(), 30000);
    }

    make() {
        this.devices_section = this.page.add_section({
            title: "Connected Devices"
        });
        this.devices_container = $("<div class='sms-devices-grid'></div>").appendTo(this.devices_section);

        this.stats_section = this.page.add_section({
            title: "Today's Statistics"
        });
        this.stats_container = $("<div class='sms-stats-grid'></div>").appendTo(this.stats_section);

        this.recent_section = this.page.add_section({
            title: "Recent Activity"
        });
        this.recent_container = $("<div class='sms-recent-list'></div>").appendTo(this.recent_section);

        this.page.set_primary_action("Refresh", () => this.refresh(), "octicon octicon-refresh");
    }

    async refresh() {
        try {
            const stats = await frappe.xcall("sms_relay.api.endpoints.get_sms_stats");
            this.render_stats(stats);

            const devices = await frappe.xcall("sms_relay.api.endpoints.get_device_health");
            this.render_devices(devices);
        } catch(e) {
            console.error("Dashboard refresh error:", e);
        }
    }

    render_stats(stats) {
        let html = `<div class="row" style="margin-top:10px;">
            <div class="col-md-3">
                <div class="card" style="padding:15px;text-align:center;border-left:4px solid #28a745;">
                    <h3 style="color:#28a745;margin:0;">${stats.sent_today || 0}</h3>
                    <p style="margin:5px 0 0;color:#666;">Sent Today</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card" style="padding:15px;text-align:center;border-left:4px solid #dc3545;">
                    <h3 style="color:#dc3545;margin:0;">${stats.failed_today || 0}</h3>
                    <p style="margin:5px 0 0;color:#666;">Failed Today</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card" style="padding:15px;text-align:center;border-left:4px solid #007bff;">
                    <h3 style="color:#007bff;margin:0;">${stats.queued || 0}</h3>
                    <p style="margin:5px 0 0;color:#666;">In Queue</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card" style="padding:15px;text-align:center;border-left:4px solid #6c757d;">
                    <h3 style="color:#6c757d;margin:0;">${stats.active_devices || 0} / ${stats.total_devices || 0}</h3>
                    <p style="margin:5px 0 0;color:#666;">Active Devices</p>
                </div>
            </div>
        </div>`;
        this.stats_container.html(html);
    }

    render_devices(devices) {
        if (!devices || devices.length === 0) {
            this.devices_container.html("<p class='text-muted'>No devices configured.</p>");
            return;
        }
        let html = '<div class="row" style="margin-top:10px;">';
        devices.forEach(d => {
            const status_color = d.is_active ? "#28a745" : "#dc3545";
            const status_text = d.is_active ? "Online" : "Offline";
            const quota_pct = d.daily_quota ? Math.round((d.sent_today / d.daily_quota) * 100) : 0;
            html += `<div class="col-md-4" style="margin-bottom:15px;">
                <div class="card" style="padding:15px;border-top:3px solid ${status_color};">
                    <h5 style="margin:0;">${d.device_name || d.name}
                        <span class="badge" style="background:${status_color};color:#fff;margin-left:8px;font-size:10px;">${status_text}</span>
                    </h5>
                    <div style="margin-top:10px;font-size:12px;color:#666;">
                        <div>SIM Slot: ${d.sim_slot || 'N/A'} | ${d.gateway_type || 'SMS'}</div>
                        <div>Battery: ${d.battery_level != null ? d.battery_level + '%' : 'N/A'} | Signal: ${d.signal_strength || 'N/A'}</div>
                        <div style="margin-top:8px;">
                            <div>Daily: ${d.sent_today || 0} / ${d.daily_quota || 0}</div>
                            <div class="progress" style="height:6px;margin-top:4px;">
                                <div class="progress-bar ${quota_pct > 80 ? 'bg-danger' : 'bg-success'}" style="width:${quota_pct}%"></div>
                            </div>
                        </div>
                        <div>Hourly: ${d.sent_this_hour || 0} / ${d.hourly_quota || 0}</div>
                    </div>
                </div>
            </div>`;
        });
        html += '</div>';
        this.devices_container.html(html);
    }
};
