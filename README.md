# SIH Smart Timetable Synthetic Dataset

## Dataset scale

- Students: 1000
- Faculty: 40
- Programs: 4
- Years: 4
- Branches: 4
- Sections: 16
- Courses: 65
- Course offerings: 144
- Rooms/resources: 27
- Teaching slots/week: 35
- Elective groups: 6

## Important modeling choices

1. A course can have multiple offerings.
2. A course can have multiple eligible faculty members.
3. A faculty member can teach multiple courses and multiple years/branches.
4. Faculty assignment is therefore not assumed to be one-to-one with a course.
5. Students have individual enrollment records, including OAE/PCE choices.
6. Labs have room-type and equipment requirements.
7. Faculty and rooms have slot-level availability.
8. Faculty availability also includes preference scores.
9. Some courses require consecutive multi-slot sessions.
10. Fixed institutional events and configurable academic rules are included.

## Main files

- universities.csv
- departments.csv
- programs.csv
- academic_terms.csv
- sections.csv
- students.csv
- courses.csv
- course_offerings.csv
- faculty.csv
- faculty_courses.csv
- faculty_availability.csv
- rooms.csv
- room_availability.csv
- time_slots.csv
- elective_groups.csv
- elective_group_courses.csv
- student_enrollments.csv
- fixed_events.csv
- academic_rules.csv
- data_dictionary.csv

This is synthetic data for software development and testing, not official university data.
