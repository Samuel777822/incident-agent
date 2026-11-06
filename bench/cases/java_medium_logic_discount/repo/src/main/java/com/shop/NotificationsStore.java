package com.shop;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Notification store for the shop. Plain map-backed so it is easy to test. */
public class NotificationsStore {
    public static class NotificationsException extends RuntimeException {
        public NotificationsException(String message) {
            super(message);
        }
    }

    private final Map<Integer, Map<String, Object>> items = new HashMap<>();
    private final List<String> audit = new ArrayList<>();
    private int nextId = 1;

    private void log(String action, int id) {
        audit.add(action + " " + id);
    }

    public int add(String name) {
        if (name == null || name.trim().isEmpty()) {
            throw new NotificationsException("name is required");
        }
        int id = nextId++;
        Map<String, Object> row = new HashMap<>();
        row.put("id", id);
        row.put("name", name.trim());
        row.put("active", Boolean.TRUE);
        items.put(id, row);
        log("add", id);
        return id;
    }

    public Map<String, Object> get(int id) {
        Map<String, Object> row = items.get(id);
        if (row == null) {
            throw new NotificationsException("Notification " + id + " not found");
        }
        return new HashMap<>(row);
    }

    public Map<String, Object> update(int id, String key, Object value) {
        Map<String, Object> row = items.get(id);
        if (row == null) {
            throw new NotificationsException("Notification " + id + " not found");
        }
        row.put(key, value);
        log("update", id);
        return new HashMap<>(row);
    }

    public void deactivate(int id) {
        update(id, "active", Boolean.FALSE);
    }

    public void delete(int id) {
        if (!items.containsKey(id)) {
            throw new NotificationsException("Notification " + id + " not found");
        }
        items.remove(id);
        log("delete", id);
    }

    public List<Map<String, Object>> list(boolean onlyActive) {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map<String, Object> row : items.values()) {
            if (!onlyActive || Boolean.TRUE.equals(row.get("active"))) {
                rows.add(new HashMap<>(row));
            }
        }
        rows.sort(Comparator.comparingInt(r -> (Integer) r.get("id")));
        return rows;
    }

    public List<Map<String, Object>> search(String text) {
        String needle = text.trim().toLowerCase();
        List<Map<String, Object>> found = new ArrayList<>();
        for (Map<String, Object> row : list(true)) {
            if (((String) row.get("name")).toLowerCase().contains(needle)) {
                found.add(row);
            }
        }
        return found;
    }

    public int count(boolean onlyActive) {
        return list(onlyActive).size();
    }

    public List<String> names() {
        List<String> out = new ArrayList<>();
        for (Map<String, Object> row : list(true)) {
            out.add((String) row.get("name"));
        }
        return out;
    }

    public List<Integer> bulkAdd(List<String> names) {
        List<Integer> ids = new ArrayList<>();
        for (String n : names) {
            ids.add(add(n));
        }
        return ids;
    }

    public String summary() {
        return "total=" + count(false) + " active=" + count(true) + " events=" + audit.size();
    }

    public List<String> auditLog() {
        return new ArrayList<>(audit);
    }
}
